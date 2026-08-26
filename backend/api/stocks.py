import math

from fastapi import APIRouter, Query, HTTPException, Body
from sqlalchemy.orm import Session
from sqlalchemy import select

from backend.database import get_db
from backend.models.models import Watchlist, WatchlistGroup
from backend.data_sources.factory import get_data_source

router = APIRouter(prefix="/api/v1/stocks", tags=["stocks"])

SYSTEM_TAGS: tuple[str, ...] = ("holding", "watching")
SYSTEM_TAG_LABELS: dict[str, str] = {"holding": "持仓", "watching": "关注"}


def _parse_tags(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [t for t in (x.strip() for x in raw.split(",")) if t]


def _serialize_tags(tags: list[str]) -> str:
    seen: list[str] = []
    for t in tags:
        if t in SYSTEM_TAGS and t not in seen:
            seen.append(t)
    return ",".join(seen)


def _stock_dict(r: Watchlist) -> dict:
    return {
        "id": r.id,
        "code": r.code,
        "name": r.name,
        "market": r.market,
        "security_type": getattr(r, "security_type", "stock") or "stock",
        "group_id": r.group_id,
        "tags": _parse_tags(r.tags),
        "target_price": r.target_price,
        "alert_diff_pct": r.alert_diff_pct,
        "cost": getattr(r, "cost", None),
        "shares": getattr(r, "shares", None),
        "planned_capital": getattr(r, "planned_capital", None),
    }


def _group_dict(g: WatchlistGroup, count: int | None = None) -> dict:
    return {
        "id": g.id,
        "name": g.name,
        "sort_order": g.sort_order or 0,
        "count": count,
    }


@router.get("/groups")
def list_groups():
    db: Session = next(get_db())
    try:
        groups = db.execute(
            select(WatchlistGroup).order_by(WatchlistGroup.sort_order.asc(), WatchlistGroup.id.asc())
        ).scalars().all()
        counts: dict[int | None, int] = {}
        tag_counts: dict[str, int] = {t: 0 for t in SYSTEM_TAGS}
        for w in db.execute(select(Watchlist)).scalars().all():
            counts[w.group_id] = counts.get(w.group_id, 0) + 1
            for t in _parse_tags(w.tags):
                if t in tag_counts:
                    tag_counts[t] += 1
        return {
            "groups": [_group_dict(g, counts.get(g.id, 0)) for g in groups],
            "ungrouped_count": counts.get(None, 0),
            "system_tags": [
                {"key": t, "name": SYSTEM_TAG_LABELS[t], "count": tag_counts[t]}
                for t in SYSTEM_TAGS
            ],
        }
    finally:
        db.close()


@router.post("/groups")
def create_group(payload: dict = Body(...)):
    name = (payload.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="分组名不能为空")
    if len(name) > 50:
        raise HTTPException(status_code=400, detail="分组名过长（最多 50 字符）")
    db: Session = next(get_db())
    try:
        existing = db.execute(select(WatchlistGroup).where(WatchlistGroup.name == name)).scalar()
        if existing:
            raise HTTPException(status_code=409, detail=f"分组 {name} 已存在")
        max_order = db.execute(select(WatchlistGroup.sort_order)).scalars().all()
        next_order = (max(max_order) + 1) if max_order else 0
        g = WatchlistGroup(name=name, sort_order=next_order)
        db.add(g)
        db.commit()
        db.refresh(g)
        return _group_dict(g, 0)
    finally:
        db.close()


@router.patch("/groups/{group_id}")
def update_group(group_id: int, payload: dict = Body(...)):
    db: Session = next(get_db())
    try:
        g = db.get(WatchlistGroup, group_id)
        if not g:
            raise HTTPException(status_code=404, detail="分组不存在")
        if "name" in payload:
            name = (payload.get("name") or "").strip()
            if not name:
                raise HTTPException(status_code=400, detail="分组名不能为空")
            if len(name) > 50:
                raise HTTPException(status_code=400, detail="分组名过长（最多 50 字符）")
            conflict = db.execute(
                select(WatchlistGroup).where(WatchlistGroup.name == name, WatchlistGroup.id != group_id)
            ).scalar()
            if conflict:
                raise HTTPException(status_code=409, detail=f"分组 {name} 已存在")
            g.name = name
        if "sort_order" in payload and payload["sort_order"] is not None:
            try:
                g.sort_order = int(payload["sort_order"])
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail="sort_order 必须为整数")
        db.commit()
        db.refresh(g)
        return _group_dict(g)
    finally:
        db.close()


@router.put("/groups/order")
def reorder_groups(payload: dict = Body(...)):
    """按 ids 数组顺序写入 sort_order（下标即顺序）。"""
    ids = payload.get("ids")
    if not isinstance(ids, list) or not all(isinstance(i, int) for i in ids):
        raise HTTPException(status_code=400, detail="ids 必须为整数数组")
    db: Session = next(get_db())
    try:
        existing = {
            g.id: g for g in db.execute(select(WatchlistGroup)).scalars().all()
        }
        unknown = [i for i in ids if i not in existing]
        if unknown:
            raise HTTPException(status_code=400, detail=f"分组不存在：{unknown}")
        for idx, gid in enumerate(ids):
            existing[gid].sort_order = idx
        db.commit()
        return {"ok": True, "count": len(ids)}
    finally:
        db.close()


@router.delete("/groups/{group_id}")
def delete_group(group_id: int):
    db: Session = next(get_db())
    try:
        g = db.get(WatchlistGroup, group_id)
        if not g:
            raise HTTPException(status_code=404, detail="分组不存在")
        for w in db.execute(select(Watchlist).where(Watchlist.group_id == group_id)).scalars().all():
            w.group_id = None
        db.delete(g)
        db.commit()
        return {"ok": True}
    finally:
        db.close()


@router.get("")
def list_watchlist(
    group_id: int | None = Query(None, description="按分组筛选；不传则返回全部"),
    ungrouped: bool = Query(False, description="只看未分组"),
    tag: str | None = Query(None, description="按系统标签过滤，如 holding / watching"),
):
    db: Session = next(get_db())
    try:
        stmt = select(Watchlist).order_by(Watchlist.added_at.desc())
        if ungrouped:
            stmt = stmt.where(Watchlist.group_id.is_(None))
        elif group_id is not None:
            stmt = stmt.where(Watchlist.group_id == group_id)
        rows = db.execute(stmt).scalars().all()
        if tag:
            tag = tag.strip()
            if tag not in SYSTEM_TAGS:
                return []
            rows = [r for r in rows if tag in _parse_tags(r.tags)]
        return [_stock_dict(r) for r in rows]
    finally:
        db.close()


@router.post("")
def add_stock(
    code: str = Query(...),
    name: str = Query(""),
    market: str = Query("A"),
    security_type: str = Query("stock"),
    group_id: int | None = Query(None),
    tags: str = Query("", description="逗号分隔的系统标签，如 watching 或 holding,watching"),
):
    db: Session = next(get_db())
    try:
        existing = db.execute(
            select(Watchlist).where(Watchlist.code == code, Watchlist.market == market)
        ).scalar()
        if existing:
            raise HTTPException(status_code=409, detail=f"Stock {code} already in watchlist")
        if group_id is not None:
            g = db.get(WatchlistGroup, group_id)
            if not g:
                raise HTTPException(status_code=400, detail="目标分组不存在")
        initial_tags = _serialize_tags(_parse_tags(tags))
        stock = Watchlist(code=code, name=name, market=market, security_type=security_type, group_id=group_id, tags=initial_tags)
        db.add(stock)
        db.commit()
        db.refresh(stock)
        return _stock_dict(stock)
    finally:
        db.close()


@router.patch("/{stock_id}")
def update_stock(stock_id: int, payload: dict = Body(...)):
    db: Session = next(get_db())
    try:
        stock = db.get(Watchlist, stock_id)
        if not stock:
            raise HTTPException(status_code=404, detail="Stock not found")
        if "group_id" in payload:
            gid = payload["group_id"]
            if gid is None:
                stock.group_id = None
            else:
                try:
                    gid_int = int(gid)
                except (TypeError, ValueError):
                    raise HTTPException(status_code=400, detail="group_id 必须为整数或 null")
                g = db.get(WatchlistGroup, gid_int)
                if not g:
                    raise HTTPException(status_code=400, detail="目标分组不存在")
                stock.group_id = gid_int
        if "tags" in payload:
            tags = payload["tags"] or []
            if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
                raise HTTPException(status_code=400, detail="tags 必须为字符串数组")
            stock.tags = _serialize_tags(tags)
        if "target_price" in payload:
            v = payload["target_price"]
            if v is None or v == "":
                stock.target_price = None
            else:
                try:
                    fv = float(v)
                except (TypeError, ValueError):
                    raise HTTPException(status_code=400, detail="target_price 必须为数字")
                if fv < 0:
                    raise HTTPException(status_code=400, detail="target_price 不能为负")
                stock.target_price = fv
        if "alert_diff_pct" in payload:
            v = payload["alert_diff_pct"]
            if v is None or v == "":
                stock.alert_diff_pct = None
            else:
                try:
                    fv = float(v)
                except (TypeError, ValueError):
                    raise HTTPException(status_code=400, detail="alert_diff_pct 必须为数字")
                if fv < 0:
                    raise HTTPException(status_code=400, detail="alert_diff_pct 不能为负")
                stock.alert_diff_pct = fv
        for field in ("cost", "shares", "planned_capital"):
            if field in payload:
                v = payload[field]
                if v is None or v == "":
                    setattr(stock, field, None)
                else:
                    try:
                        fv = float(v)
                    except (TypeError, ValueError):
                        raise HTTPException(status_code=400, detail=f"{field} 必须为数字")
                    if not math.isfinite(fv):
                        raise HTTPException(status_code=400, detail=f"{field} 必须为有效数字")
                    if fv < 0:
                        raise HTTPException(status_code=400, detail=f"{field} 不能为负")
                    setattr(stock, field, fv)
        db.commit()
        db.refresh(stock)
        return _stock_dict(stock)
    finally:
        db.close()


@router.delete("/{stock_id}")
def delete_stock(stock_id: int):
    db: Session = next(get_db())
    try:
        stock = db.get(Watchlist, stock_id)
        if not stock:
            raise HTTPException(status_code=404, detail="Stock not found")
        db.delete(stock)
        db.commit()
        return {"ok": True}
    finally:
        db.close()


@router.get("/search")
def search_stocks(q: str = Query(..., min_length=1)):
    ds = get_data_source()
    results = ds.search_stocks(q)
    return {"query": q, "results": results}
