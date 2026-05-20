"""Azure Blob Storage upload helper."""

from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient


def upload_blob(file, account_name: str, container_name: str) -> str:
    """Upload a file-like object to Azure Blob Storage.

    Overwrites any existing blob with the same name.
    Returns the blob name on success; raises on failure.
    """
    credential = DefaultAzureCredential()
    service_client = BlobServiceClient(
        account_url=f"https://{account_name}.blob.core.windows.net",
        credential=credential,
    )
    container_client = service_client.get_container_client(container_name)
    blob_client = container_client.get_blob_client(file.name)
    blob_client.upload_blob(file, overwrite=True)
    return file.name
