"""0.75–0.45 2단 홀 편심·가림·방향 분석."""
from __future__ import annotations

import math
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"}

# 물리 직경(mm) — 픽셀 환산용
LARGE_DIAM_MM = 0.75
SMALL_DIAM_MM = 0.45

# 가림률(%) 초과 시 가려진 홀 / 불합격
DEFAULT_OCCLUSION_PCT = 2.0

DIRECTION_LABELS_8 = (
    "동",
    "동남",
    "남",
    "남서",
    "서",
    "서북",
    "북",
    "북동",
)


@dataclass
class HoleResult:
    file_name: str
    file_path: str
    ok: bool
    error: str = ""
    large_cx: float = float("nan")
    large_cy: float = float("nan")
    large_r_px: float = float("nan")
    small_cx: float = float("nan")
    small_cy: float = float("nan")
    small_r_px: float = float("nan")
    offset_px: float = float("nan")
    offset_mm: float = float("nan")
    offset_norm: float = float("nan")
    clearance_px: float = float("nan")
    angle_deg: float = float("nan")
    direction: str = ""
    occlusion_pct: float = float("nan")
    occluded: bool = False
    passed: bool = False
    px_per_mm: float = float("nan")


def list_image_files(folder: str | Path, *, recursive: bool = True) -> list[Path]:
    root = Path(folder)
    if not root.is_dir():
        return []
    it = root.rglob("*") if recursive else root.iterdir()
    files = [p for p in it if p.is_file() and p.suffix.lower() in IMAGE_EXTS]
    return sorted(files, key=lambda p: str(p).lower())


def _circularity(area: float, peri: float) -> float:
    if peri <= 1e-6 or area <= 1e-6:
        return 0.0
    return float(4.0 * math.pi * area / (peri * peri))


def _fit_circle_least_squares(points: np.ndarray) -> tuple[float, float, float] | None:
    """points: (N,2) → (cx, cy, r)."""
    if points is None or len(points) < 8:
        return None
    pts = np.asarray(points, dtype=np.float64).reshape(-1, 2)
    if pts.shape[0] < 8:
        return None
    x = pts[:, 0]
    y = pts[:, 1]
    A = np.column_stack([2 * x, 2 * y, np.ones_like(x)])
    try:
        sol, _, _, _ = np.linalg.lstsq(A, x * x + y * y, rcond=None)
    except np.linalg.LinAlgError:
        return None
    cx, cy, c = float(sol[0]), float(sol[1]), float(sol[2])
    r2 = c + cx * cx + cy * cy
    if r2 <= 1.0:
        return None
    return cx, cy, float(math.sqrt(r2))


def _remove_border_connected(mask: np.ndarray) -> np.ndarray:
    """가장자리와 연결된 흰색 영역을 제거 (배경 제거)."""
    import cv2

    out = mask.copy()
    h, w = out.shape[:2]
    ff_mask = np.zeros((h + 2, w + 2), np.uint8)
    for seed in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)):
        if out[seed[1], seed[0]] != 0:
            cv2.floodFill(out, ff_mask, seed, 0)
    return out


def _best_circular_contour(
    mask: np.ndarray,
    *,
    min_area: float,
    max_area: float | None = None,
) -> tuple[np.ndarray, float, float, float, float] | None:
    """가장 원형에 가까운 컨투어 → (contour, cx, cy, r, score)."""
    import cv2

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    best = None
    best_score = -1.0
    for cnt in contours:
        area = float(cv2.contourArea(cnt))
        if area < min_area:
            continue
        if max_area is not None and area > max_area:
            continue
        peri = float(cv2.arcLength(cnt, True))
        circ = _circularity(area, peri)
        if circ < 0.55:
            continue
        (cx, cy), r = cv2.minEnclosingCircle(cnt)
        fill = area / (math.pi * r * r + 1e-6)
        score = circ * 0.7 + min(fill, 1.0) * 0.3
        if score > best_score:
            best_score = score
            best = (cnt, float(cx), float(cy), float(r), score)
    return best


def _detect_small_hole(gray: np.ndarray) -> tuple[float, float, float] | None:
    import cv2

    h, w = gray.shape[:2]
    area_img = float(h * w)
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    # 작은 홀은 밝고 작음 — 반지름 상한으로 외곽 링 혼입 방지
    max_r = min(h, w) * 0.28
    max_area = math.pi * max_r * max_r

    thr_candidates = []
    p95 = float(np.percentile(blur, 95))
    p90 = float(np.percentile(blur, 90))
    for t in (max(140.0, p90), max(160.0, p95), 180.0, 200.0, 220.0):
        thr_candidates.append(int(min(250, t)))

    best = None
    best_score = -1.0
    for t in sorted(set(thr_candidates)):
        _, bw = cv2.threshold(blur, t, 255, cv2.THRESH_BINARY)
        bw = cv2.morphologyEx(bw, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
        contours, _ = cv2.findContours(bw, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for cnt in contours:
            area = float(cv2.contourArea(cnt))
            if area < max(20.0, area_img * 0.0005) or area > max_area:
                continue
            peri = float(cv2.arcLength(cnt, True))
            circ = _circularity(area, peri)
            if circ < 0.55:
                continue
            (cx, cy), r = cv2.minEnclosingCircle(cnt)
            if r > max_r:
                continue
            mask = np.zeros((h, w), np.uint8)
            cv2.drawContours(mask, [cnt], -1, 255, -1)
            mean_i = float(cv2.mean(blur, mask=mask)[0])
            fill = area / (math.pi * r * r + 1e-6)
            score = circ * 0.35 + min(fill, 1.0) * 0.2 + (mean_i / 255.0) * 0.45
            if score > best_score:
                best_score = score
                best = (float(cx), float(cy), float(r))

    if best is not None:
        return best

    _, bw = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    hit = _best_circular_contour(
        bw,
        min_area=max(20.0, area_img * 0.0005),
        max_area=max_area,
    )
    if hit is None:
        return None
    return hit[1], hit[2], hit[3]


def _detect_large_hole(
    gray: np.ndarray,
    small: tuple[float, float, float] | None,
) -> tuple[float, float, float] | None:
    import cv2

    h, w = gray.shape[:2]
    area_img = float(h * w)
    blur = cv2.GaussianBlur(gray, (5, 5), 0)

    thr = max(25, int(np.percentile(blur[blur > 5], 35)) if np.any(blur > 5) else 40)
    _, ring = cv2.threshold(blur, thr, 255, cv2.THRESH_BINARY)
    ring = cv2.morphologyEx(ring, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))

    _, dark = cv2.threshold(blur, thr, 255, cv2.THRESH_BINARY_INV)
    cavity = _remove_border_connected(dark)

    if small is not None:
        sx, sy, sr = small
        cv2.circle(cavity, (int(round(sx)), int(round(sy))), int(round(sr * 1.15)), 255, -1)

    cavity = cv2.morphologyEx(cavity, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    hit = _best_circular_contour(
        cavity,
        min_area=max(80.0, area_img * 0.01),
        max_area=area_img * 0.85,
    )
    if hit is not None:
        cnt, cx, cy, r, _ = hit
        fitted = _fit_circle_least_squares(cnt.reshape(-1, 2))
        if fitted is not None:
            return fitted
        return cx, cy, r

    contours, hierarchy = cv2.findContours(ring, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    if hierarchy is not None:
        hierarchy = hierarchy[0]
        candidates: list[tuple[float, float, float, float]] = []
        for i, cnt in enumerate(contours):
            if hierarchy[i][3] < 0:
                continue
            area = float(cv2.contourArea(cnt))
            if area < area_img * 0.01:
                continue
            peri = float(cv2.arcLength(cnt, True))
            circ = _circularity(area, peri)
            if circ < 0.5:
                continue
            fitted = _fit_circle_least_squares(cnt.reshape(-1, 2))
            if fitted is None:
                (cx, cy), r = cv2.minEnclosingCircle(cnt)
            else:
                cx, cy, r = fitted
            candidates.append((circ * area, cx, cy, r))
        if candidates:
            candidates.sort(reverse=True)
            _, cx, cy, r = candidates[0]
            return float(cx), float(cy), float(r)

    min_r = int(min(h, w) * 0.12)
    max_r = int(min(h, w) * 0.55)
    circles = cv2.HoughCircles(
        blur,
        cv2.HOUGH_GRADIENT,
        dp=1.2,
        minDist=min(h, w) // 2,
        param1=120,
        param2=30,
        minRadius=min_r,
        maxRadius=max_r,
    )
    if circles is not None:
        c = circles[0][0]
        return float(c[0]), float(c[1]), float(c[2])
    return None


def angle_to_direction8(angle_deg: float) -> str:
    """이미지 좌표(x右, y下)에서 atan2(-dy, dx) 기준 0°=동, 90°=북."""
    if not math.isfinite(angle_deg):
        return ""
    a = angle_deg % 360.0
    idx = int((a + 22.5) // 45.0) % 8
    return DIRECTION_LABELS_8[idx]


def occlusion_percent(
    large_cx: float,
    large_cy: float,
    large_r: float,
    small_cx: float,
    small_cy: float,
    small_r: float,
) -> float:
    """작은 원 면적 중 큰 원 밖에 있는 비율(%)."""
    if small_r <= 1e-6:
        return 0.0
    r = int(math.ceil(small_r)) + 2
    ys, xs = np.mgrid[-r : r + 1, -r : r + 1]
    disk = xs * xs + ys * ys <= small_r * small_r
    if not np.any(disk):
        return 0.0
    gx = small_cx + xs
    gy = small_cy + ys
    outside = (gx - large_cx) ** 2 + (gy - large_cy) ** 2 > large_r * large_r
    occluded = disk & outside
    return float(occluded.sum()) / float(disk.sum()) * 100.0


def analyze_array(
    gray: np.ndarray,
    *,
    file_name: str = "",
    file_path: str = "",
    occlusion_limit_pct: float = DEFAULT_OCCLUSION_PCT,
) -> HoleResult:
    if gray is None or gray.size == 0:
        return HoleResult(file_name=file_name, file_path=file_path, ok=False, error="이미지 로드 실패")

    if gray.ndim == 3:
        import cv2

        gray = cv2.cvtColor(gray, cv2.COLOR_BGR2GRAY)

    small = _detect_small_hole(gray)
    large = _detect_large_hole(gray, small)
    if small is None or large is None:
        return HoleResult(
            file_name=file_name,
            file_path=file_path,
            ok=False,
            error="홀 검출 실패",
        )

    sx, sy, sr = small
    lx, ly, lr = large
    if lr < sr * 1.05 and sr > lr:
        sx, sy, sr, lx, ly, lr = lx, ly, lr, sx, sy, sr

    dx = sx - lx
    dy = sy - ly
    offset = math.hypot(dx, dy)
    angle = math.degrees(math.atan2(-dy, dx)) % 360.0
    direction = angle_to_direction8(angle)
    px_per_mm = (2.0 * lr) / LARGE_DIAM_MM if lr > 1e-6 else float("nan")
    offset_mm = offset / px_per_mm if px_per_mm and math.isfinite(px_per_mm) else float("nan")
    offset_norm = offset / lr if lr > 1e-6 else float("nan")
    clearance = (lr - sr) - offset
    occ = occlusion_percent(lx, ly, lr, sx, sy, sr)
    occluded = occ > occlusion_limit_pct
    passed = (not occluded) and clearance > 0

    return HoleResult(
        file_name=file_name,
        file_path=file_path,
        ok=True,
        large_cx=lx,
        large_cy=ly,
        large_r_px=lr,
        small_cx=sx,
        small_cy=sy,
        small_r_px=sr,
        offset_px=offset,
        offset_mm=offset_mm,
        offset_norm=offset_norm,
        clearance_px=clearance,
        angle_deg=angle,
        direction=direction,
        occlusion_pct=occ,
        occluded=occluded,
        passed=passed,
        px_per_mm=px_per_mm,
    )


def analyze_image_path(
    path: str | Path,
    *,
    occlusion_limit_pct: float = DEFAULT_OCCLUSION_PCT,
) -> HoleResult:
    import cv2

    p = Path(path)
    img = cv2.imread(str(p), cv2.IMREAD_GRAYSCALE)
    return analyze_array(
        img,
        file_name=p.name,
        file_path=str(p),
        occlusion_limit_pct=occlusion_limit_pct,
    )


def _analyze_worker(args: tuple[str, float]) -> dict:
    path, limit = args
    return asdict(analyze_image_path(path, occlusion_limit_pct=limit))


def analyze_folder(
    folder: str | Path,
    *,
    occlusion_limit_pct: float = DEFAULT_OCCLUSION_PCT,
    recursive: bool = True,
    max_workers: int | None = None,
    progress_cb=None,
) -> pd.DataFrame:
    files = list_image_files(folder, recursive=recursive)
    if not files:
        return results_to_frame([])

    rows: list[dict] = []
    payloads = [(str(p), float(occlusion_limit_pct)) for p in files]
    total = len(payloads)

    if max_workers is None or max_workers <= 1:
        for i, payload in enumerate(payloads, start=1):
            rows.append(_analyze_worker(payload))
            if progress_cb is not None:
                progress_cb(i, total, payload[0])
    else:
        with ProcessPoolExecutor(max_workers=max_workers) as ex:
            futs = {ex.submit(_analyze_worker, p): p for p in payloads}
            done = 0
            for fut in as_completed(futs):
                rows.append(fut.result())
                done += 1
                if progress_cb is not None:
                    progress_cb(done, total, futs[fut][0])

    frame = results_to_frame(rows)
    if not frame.empty:
        frame = frame.sort_values("file_name", kind="mergesort").reset_index(drop=True)
    return frame


def results_to_frame(rows: Iterable[dict | HoleResult]) -> pd.DataFrame:
    data = []
    for row in rows:
        if isinstance(row, HoleResult):
            data.append(asdict(row))
        else:
            data.append(dict(row))
    if not data:
        cols = list(asdict(HoleResult(file_name="", file_path="", ok=False)).keys())
        return pd.DataFrame(columns=cols)
    return pd.DataFrame(data)


def summarize_results(
    df: pd.DataFrame,
    *,
    occlusion_limit_pct: float = DEFAULT_OCCLUSION_PCT,
) -> dict:
    total = int(len(df))
    if total == 0:
        return {
            "total": 0,
            "detected": 0,
            "failed_detect": 0,
            "occluded_count": 0,
            "occluded_ratio_pct": 0.0,
            "pass_count": 0,
            "fail_count": 0,
            "occlusion_limit_pct": occlusion_limit_pct,
        }

    ok = df["ok"] == True  # noqa: E712
    detected = int(ok.sum())
    failed = total - detected
    valid = df.loc[ok].copy()

    def _stats(series: pd.Series) -> dict:
        s = pd.to_numeric(series, errors="coerce").dropna()
        if s.empty:
            return {
                "mean": float("nan"),
                "median": float("nan"),
                "std": float("nan"),
                "min": float("nan"),
                "max": float("nan"),
                "p90": float("nan"),
                "p95": float("nan"),
                "p99": float("nan"),
            }
        return {
            "mean": float(s.mean()),
            "median": float(s.median()),
            "std": float(s.std(ddof=0)),
            "min": float(s.min()),
            "max": float(s.max()),
            "p90": float(s.quantile(0.90)),
            "p95": float(s.quantile(0.95)),
            "p99": float(s.quantile(0.99)),
        }

    occluded_count = int(valid["occluded"].fillna(False).astype(bool).sum()) if detected else 0
    pass_count = int(valid["passed"].fillna(False).astype(bool).sum()) if detected else 0
    fail_count = detected - pass_count
    occ_ratio = (occluded_count / detected * 100.0) if detected else 0.0

    dir_counts = (
        valid["direction"].value_counts().reindex(DIRECTION_LABELS_8, fill_value=0).astype(int)
        if detected
        else pd.Series({d: 0 for d in DIRECTION_LABELS_8})
    )
    dominant = ""
    if detected and int(dir_counts.sum()) > 0:
        dominant = str(dir_counts.idxmax())

    return {
        "total": total,
        "detected": detected,
        "failed_detect": failed,
        "occluded_count": occluded_count,
        "not_occluded_count": max(0, detected - occluded_count),
        "occluded_ratio_pct": float(occ_ratio),
        "pass_count": pass_count,
        "fail_count": fail_count,
        "occlusion_limit_pct": occlusion_limit_pct,
        "occlusion": _stats(valid["occlusion_pct"]) if detected else _stats(pd.Series(dtype=float)),
        "offset_px": _stats(valid["offset_px"]) if detected else _stats(pd.Series(dtype=float)),
        "offset_mm": _stats(valid["offset_mm"]) if detected else _stats(pd.Series(dtype=float)),
        "offset_norm": _stats(valid["offset_norm"]) if detected else _stats(pd.Series(dtype=float)),
        "clearance_px": _stats(valid["clearance_px"]) if detected else _stats(pd.Series(dtype=float)),
        "negative_clearance_count": int((valid["clearance_px"] <= 0).sum()) if detected else 0,
        "direction_counts": {k: int(v) for k, v in dir_counts.items()},
        "direction_dominant": dominant,
        "product_pass": bool(detected > 0 and fail_count == 0 and failed == 0),
    }


def draw_overlay(gray_or_bgr: np.ndarray, result: HoleResult) -> np.ndarray:
    import cv2

    if gray_or_bgr.ndim == 2:
        vis = cv2.cvtColor(gray_or_bgr, cv2.COLOR_GRAY2BGR)
    else:
        vis = gray_or_bgr.copy()
    if not result.ok:
        cv2.putText(vis, result.error or "FAIL", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
        return vis

    lx, ly, lr = int(round(result.large_cx)), int(round(result.large_cy)), int(round(result.large_r_px))
    sx, sy, sr = int(round(result.small_cx)), int(round(result.small_cy)), int(round(result.small_r_px))
    color_large = (80, 200, 80)
    color_small = (0, 200, 255) if result.passed else (40, 40, 255)
    cv2.circle(vis, (lx, ly), lr, color_large, 2)
    cv2.drawMarker(vis, (lx, ly), color_large, cv2.MARKER_CROSS, 12, 2)
    cv2.circle(vis, (sx, sy), sr, color_small, 2)
    cv2.drawMarker(vis, (sx, sy), color_small, cv2.MARKER_CROSS, 12, 2)
    cv2.line(vis, (lx, ly), (sx, sy), (255, 180, 80), 2)
    label = f"{result.direction} {result.offset_mm:.4f}mm occ {result.occlusion_pct:.1f}%"
    cv2.putText(vis, label, (10, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (240, 240, 240), 2)
    return vis


def top_rows(df: pd.DataFrame, column: str, n: int = 10) -> pd.DataFrame:
    if df is None or df.empty or column not in df.columns:
        return pd.DataFrame()
    valid = df[df["ok"] == True].copy()  # noqa: E712
    if valid.empty:
        return valid
    return valid.sort_values(column, ascending=False).head(n)
