from flask import Flask, request, jsonify
from werkzeug.utils import secure_filename
from PIL import Image
from io import BytesIO
from azure.storage.blob import BlobServiceClient, generate_blob_sas, BlobSasPermissions
from datetime import datetime, timedelta
import os
from flask_cors import CORS
# Flask app setup
app = Flask(__name__)
CORS(app)
# Azure Blob Storage configuration
AZURE_CONNECTION_STRING = "DefaultEndpointsProtocol=https;AccountName=deepproject;AccountKey=upQTjDRh/OSZg6VPOe5tHE9kvYr8cVpN/3ojGHF6MbXqQiJFmulpc7paiVbwYjwfHirrEveMVSDz+ASt9jFsjA==;EndpointSuffix=core.windows.net"
AZURE_CONTAINER_NAME = "image-service"

# Maximum file size: 10 MB
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB

# Allowed image formats
ALLOWED_FORMATS = {"JPEG", "JPG", "PNG", "WEBP", "HEIC", "HEIF"}

# Initialize Azure BlobServiceClient
blob_service_client = BlobServiceClient.from_connection_string(AZURE_CONNECTION_STRING)


def is_valid_image(file_data):
    """Validate if the file is an image and within the allowed formats."""
    try:
        img = Image.open(file_data)
        if img.format.upper() not in ALLOWED_FORMATS:
            return False, f"Unsupported image format: {img.format}"
        return True, None
    except Exception as e:
        return False, f"Error: {str(e)}"


def compress_image(file_data, size_reduction_mb=2, quality=85, max_width=1920):
    """Compress the image and resize it in memory."""
    img = Image.open(file_data)
    width, height = img.size

    # Resize image while maintaining aspect ratio
    if width > max_width:
        new_height = int(height * max_width / width)
        img = img.resize((max_width, new_height), Image.Resampling.LANCZOS)

    # Save compressed image to memory
    compressed_image = BytesIO()
    img.save(compressed_image, format="JPEG", optimize=True, quality=quality)
    compressed_image.seek(0)

    return compressed_image


def upload_image_to_cloud(file_data, blob_name):
    """Upload an image to Azure Blob Storage and generate a SAS URL."""
    # Get a BlobClient to interact with the blob
    blob_client = blob_service_client.get_blob_client(container=AZURE_CONTAINER_NAME, blob=blob_name)

    # Upload the image data to the blob
    blob_client.upload_blob(file_data, overwrite=True)

    # Generate a SAS token with read permissions
    sas_token = generate_blob_sas(
        account_name=blob_service_client.account_name,
        container_name=AZURE_CONTAINER_NAME,
        blob_name=blob_name,
        account_key=blob_service_client.credential.account_key,
        permission=BlobSasPermissions(read=True),
        expiry=datetime.utcnow() + timedelta(days=365 * 100)  # 100 years expiry
    )

    # Generate SAS URL
    sas_url = f"https://{blob_service_client.account_name}.blob.core.windows.net/{AZURE_CONTAINER_NAME}/{blob_name}?{sas_token}"

    return sas_url


@app.route("/upload", methods=["POST"])
def upload_image():
    """Endpoint to handle image uploads, compression, and upload to Azure."""
    if "file" not in request.files:
        return jsonify({"error": "No file part in the request"}), 400

    file = request.files["file"]
    if file.filename == "":
        return jsonify({"error": "No selected file"}), 400

    # Check file size
    file.seek(0, os.SEEK_END)
    file_size = file.tell()
    file.seek(0)

    if file_size > MAX_FILE_SIZE:
        return jsonify({"error": "File size exceeds 10 MB"}), 400

    # Validate the image
    is_valid, error = is_valid_image(file)
    if not is_valid:
        return jsonify({"error": error}), 400

    # Compress the image
    compressed_image = compress_image(file)

    # Create a secure filename and upload the compressed image to Azure
    blob_name = secure_filename(file.filename)
    sas_url = upload_image_to_cloud(compressed_image, blob_name)

    return jsonify({
        "message": "File uploaded and processed successfully",
        "access_url": sas_url
    })


if __name__ == "__main__":
    app.run(debug=True)
