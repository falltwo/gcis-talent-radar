"""Education directory, campus search, and campus details APIs."""
from fastapi import APIRouter, HTTPException, Query
from engine.campus_details import campus_detail, EducationEntityNotFound
from engine.education_directory import (
    EducationDataUnavailable, get_education_coverage,
    list_education_institutions, search_education_departments, search_education_campuses,
)

router = APIRouter(prefix='/api/education', tags=['Education directory'])


def _read(fn, **kwargs):
    try:
        return fn(**kwargs)
    except EducationDataUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except EducationEntityNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get('/coverage')
def coverage():
    return _read(get_education_coverage)


@router.get('/institutions')
def institutions():
    return _read(list_education_institutions)


@router.get('/campuses')
def campuses(latitude: float = Query(..., ge=-90, le=90),
             longitude: float = Query(..., ge=-180, le=180),
             radius_km: float = Query(15, gt=0), q: str = Query('', max_length=80), include_related: bool = False):
    return _read(search_education_campuses, latitude=latitude, longitude=longitude,
                 radius_km=radius_km, q=q, include_related=include_related)


@router.get('/campuses/{campus_id}')
def get_campus_detail(campus_id: str, release_id: str | None = None):
    return _read(campus_detail, campus_id=campus_id, release_id=release_id)


@router.get('/departments')
def departments(q: str = Query('', max_length=80), institution_id: str | None = None,
                district: str | None = None, page: int = Query(1, ge=1),
                page_size: int = Query(50, ge=1, le=100), release_id: str | None = None):
    return _read(search_education_departments, q=q, institution_id=institution_id,
                 district=district, page=page, page_size=page_size, release_id=release_id)
