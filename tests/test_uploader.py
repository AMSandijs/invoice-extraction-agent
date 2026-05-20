from unittest.mock import MagicMock, patch

import pytest

from uploader import upload_blob


@pytest.fixture
def fake_file():
    f = MagicMock()
    f.name = "invoice.pdf"
    f.read.return_value = b"%PDF fake content"
    return f


def test_upload_blob_calls_azure_with_correct_args(fake_file):
    mock_blob_client = MagicMock()
    mock_container_client = MagicMock()
    mock_container_client.get_blob_client.return_value = mock_blob_client
    mock_service_client = MagicMock()
    mock_service_client.get_container_client.return_value = mock_container_client

    with patch("uploader.BlobServiceClient") as MockBSC, \
         patch("uploader.DefaultAzureCredential"):
        MockBSC.return_value = mock_service_client
        result = upload_blob(fake_file, "myaccount", "mycontainer")

    # Check that BlobServiceClient was called with correct account_url and a credential was passed
    assert MockBSC.call_count == 1
    call_kwargs = MockBSC.call_args[1]
    assert call_kwargs["account_url"] == "https://myaccount.blob.core.windows.net"
    assert "credential" in call_kwargs

    mock_service_client.get_container_client.assert_called_once_with("mycontainer")
    mock_container_client.get_blob_client.assert_called_once_with("invoice.pdf")
    mock_blob_client.upload_blob.assert_called_once_with(fake_file, overwrite=True)
    assert result == "invoice.pdf"


def test_upload_blob_returns_blob_name(fake_file):
    with patch("uploader.BlobServiceClient"), \
         patch("uploader.DefaultAzureCredential"):
        result = upload_blob(fake_file, "acc", "cont")
    assert result == "invoice.pdf"


def test_upload_blob_propagates_errors(fake_file):
    with patch("uploader.BlobServiceClient") as MockBSC, \
         patch("uploader.DefaultAzureCredential"):
        MockBSC.return_value.get_container_client.return_value \
            .get_blob_client.return_value \
            .upload_blob.side_effect = RuntimeError("network error")
        with pytest.raises(RuntimeError, match="network error"):
            upload_blob(fake_file, "acc", "cont")
