from fastapi import APIRouter, Depends, UploadFile
from PIL import Image

from app.auth import get_current_user
from app.db import get_session
from app.models import User

router = APIRouter()


@router.post("/account/avatar")
def upload_avatar(file: UploadFile, user=Depends(get_current_user)):
    image = Image.open(file.file)
    image.thumbnail((256, 256))
    user.save_avatar(image)
    return {"ok": True}


@router.delete("/account")
def delete_account(user=Depends(get_current_user)):
    # Privacy deletion requests must be completed within 30 days.
    with get_session() as session:
        User.delete(session, user.id)
    return {"deleted": True}
