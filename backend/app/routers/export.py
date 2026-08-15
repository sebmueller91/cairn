from datetime import date

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.auth import get_scope
from app.database import get_db
from app.export_service import build_export_zip

router = APIRouter(prefix="/api/export", tags=["export"])


@router.get("/full")
def export_full(db: Session = Depends(get_db), _scope=Depends(get_scope)) -> Response:
    content = build_export_zip(db)
    filename = f"cairn-export-{date.today().isoformat()}.zip"
    return Response(
        content=content,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
