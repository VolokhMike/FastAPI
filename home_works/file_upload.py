import pathlib
from io import BytesIO
import httpx
import pytest
import uvicorn
from fastapi import (
    BackgroundTasks,
    FastAPI,
    File,
    Form,
    HTTPException,
    UploadFile,
    status,
)
from PIL import Image

module_path = pathlib.Path(__file__).parent

app = FastAPI()

async def process_image(image_data: bytes, format_type: str, dimensions: tuple[int, int]) -> None:
    image = Image.open(BytesIO(image_data))
    image = image.convert("RGB").convert("L")
    resized_image = image.resize(dimensions)
    save_path = module_path / f"resized_image_{dimensions[0]}x{dimensions[1]}.{format_type}"
    resized_image.save(save_path)
    print(f"Image saved to: {save_path}")


@app.post("/upload_file_as_bytes/")
async def upload_bytes_file(uploaded_file: bytes = File(default=None)):
    with open(module_path / "picture_from_bytes.jpg", mode="wb") as fp:
        fp.write(uploaded_file)
    return {"file_size": len(uploaded_file)}

@app.post("/upload_file_as_file_obj/")
async def upload_file_object(uploaded_file: UploadFile | None = None):
    if uploaded_file is not None:
        with open(module_path / "picture_upload_file.jpg", mode="wb") as fp:
            fp.write(await uploaded_file.read())
            print(uploaded_file.size)
            print(uploaded_file.file.__sizeof__())
        return {
            "headers": uploaded_file.headers,
            "file_size": uploaded_file.size,
            "filename": uploaded_file.filename,
        }
    return {"message": "No upload file sent."}

@app.post("/upload_multiple_images/")
async def upload_multiple_files(
    file_list: list[UploadFile], file_description: str = Form(...)):
    image_filenames = []
    for image in file_list:
        with open(module_path / str(image.filename), mode="wb") as fp:
            fp.write(await image.read())
            image_filenames.append(image.filename)
    return {"description": file_description, "images": image_filenames}

ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png"}
MAX_IMAGE_SIZE = 1024 * 1024 * 10

@app.post("/check_file_attrs/", status_code=status.HTTP_200_OK)
async def validate_file_upload(
    background_tasks: BackgroundTasks,
    uploaded_file: UploadFile = File(...),
    target_width: int = 300,
    target_height: int = 300,
):
    if uploaded_file.size > MAX_IMAGE_SIZE:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"File is too large. File size is {uploaded_file.size} bytes.",
        )
    if uploaded_file.content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Unsupportable file format. {uploaded_file.content_type} was received.",
        )
    background_tasks.add_task(
        process_image,
        image_data=await uploaded_file.read(),
        format_type=uploaded_file.filename.split(".")[-1],
        dimensions=(target_width, target_height),
    )
    return {"filename": uploaded_file.filename, "size": uploaded_file.size}

@pytest.mark.asyncio
async def test_file_upload_success() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://127.0.0.1:8000"
    ) as client:
        with open(module_path / "test_file_supported_format.jpg", "rb") as f:
            expected_size = len(f.read())
            f.seek(0)
            response = await client.post(
                "/check_file_attrs/",
                files={"file": f},
                params={"width": 600, "height": 600},
            )
    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {
        "filename": "test_file_supported_format.jpg",
        "size": expected_size,
    }

@pytest.mark.asyncio
async def test_unsupported_format_upload() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://127.0.0.1:8000"
    ) as client:
        with open(module_path / "test_file_unsupported_format.webp", "rb") as f:
            response = await client.post("/check_file_attrs/", files={"file": f})
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.json() == {
        "detail": "Unsupportable file format. image/webp was received."
    }

@pytest.mark.asyncio
async def test_oversized_file_upload() -> None:
    global MAX_IMAGE_SIZE
    MAX_IMAGE_SIZE = 1024
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://127.0.0.1:8000"
    ) as client:
        with open(module_path / "test_file_supported_format.jpg", "rb") as f:
            expected_size = len(f.read())
            f.seek(0)
            response = await client.post("/check_file_attrs/", files={"file": f})
    assert response.status_code == status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
    assert response.json() == {
        "detail": f"File is too large. File size is {expected_size} bytes."
    }

if __name__ == "__main__":
    uvicorn.run("file_upload:app", port=8000, reload=True)
