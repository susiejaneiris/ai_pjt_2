"""마스코트 '로우' 한 장(8자세) → 자세별 투명 PNG. 한 번만 실행합니다.

실행 (프로젝트 폴더에서):
    python -m scripts.cut_mascot

assets/mascot/law_sheet.png → assets/mascot/{gavel,reading,thinking,scale,wave,desk,magnifier,walking}.png
                            + assets/mascot/avatar.png (채팅 말풍선용 얼굴)

1. 배경 지우기 — 원본의 체크무늬는 투명이 아니라 그려진 무늬(RGB)다.
   체크무늬는 밝은 무채색, 로우의 몸은 붉은 기가 도는 크림색이라
   "가장자리에서 이어진 밝은 무채색 픽셀"만 배경으로 지운다 → 셔츠 깃 · 렌즈처럼 안쪽의 흰 부분은 남는다.
2. 자세 나누기 — 격자로 자르면 안 된다 (위 줄 발이 가운데 선을 넘고, 손 흔드는 로우와 책상이 세로로 겹친다).
   연결된 덩어리를 찾아 큰 것 8개를 캐릭터로, 작은 것(! ? ♪ ✦)은 가장 가까운 캐릭터에 붙인다.
"""

from collections import deque

import numpy as np
from PIL import Image, ImageFilter

from config import ROOT

SHEET = ROOT / "assets" / "mascot" / "law_sheet.png"
OUT_DIR = SHEET.parent
POSES = ["gavel", "reading", "thinking", "scale",      # 위 줄 왼쪽부터
         "wave", "desk", "magnifier", "walking"]       # 아래 줄 왼쪽부터
SCALE = 4                                              # 덩어리 찾기는 1/4 크기에서
NO_EXTRAS = {"desk"}     # 원본에서 장식이 없는 자세 — 옆 돋보기 로우의 강조선이 거리상 더 가까워 잘못 붙는다


def background_mask(rgb: np.ndarray) -> np.ndarray:
    """가장자리에서 이어진 밝은 무채색 영역 = 배경."""
    r, b = rgb[..., 0].astype(int), rgb[..., 2].astype(int)
    spread = np.max(rgb, axis=2).astype(int) - np.min(rgb, axis=2).astype(int)
    candidate = (spread <= 7) & (np.min(rgb, axis=2) >= 222) & (b >= r - 2)

    mask = np.zeros_like(candidate)
    mask[0, :], mask[-1, :], mask[:, 0], mask[:, -1] = candidate[0, :], candidate[-1, :], candidate[:, 0], candidate[:, -1]
    while True:                                   # 이웃으로 번지기 (flood fill)
        grown = mask.copy()
        grown[1:, :] |= mask[:-1, :]
        grown[:-1, :] |= mask[1:, :]
        grown[:, 1:] |= mask[:, :-1]
        grown[:, :-1] |= mask[:, 1:]
        grown &= candidate
        if (grown == mask).all():
            return mask
        mask = grown


def label_components(mask: np.ndarray) -> tuple[np.ndarray, list[dict]]:
    """8방향으로 이어진 덩어리에 번호를 붙인다."""
    labels = np.zeros(mask.shape, dtype=int)
    comps = []
    h, w = mask.shape
    for y0, x0 in zip(*np.nonzero(mask)):
        if labels[y0, x0]:
            continue
        n = len(comps) + 1
        labels[y0, x0] = n
        queue, cells = deque([(y0, x0)]), []
        while queue:
            y, x = queue.popleft()
            cells.append((y, x))
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    ny, nx = y + dy, x + dx
                    if 0 <= ny < h and 0 <= nx < w and mask[ny, nx] and not labels[ny, nx]:
                        labels[ny, nx] = n
                        queue.append((ny, nx))
        ys, xs = zip(*cells)
        comps.append({"id": n, "size": len(cells), "box": (min(xs), min(ys), max(xs) + 1, max(ys) + 1)})
    return labels, comps


def box_distance(a: tuple, b: tuple) -> float:
    dx = max(a[0] - b[2], b[0] - a[2], 0)
    dy = max(a[1] - b[3], b[1] - a[3], 0)
    return (dx * dx + dy * dy) ** 0.5


def main() -> None:
    rgb = np.array(Image.open(SHEET).convert("RGB"))
    alpha = np.where(background_mask(rgb), 0, 255).astype(np.uint8)
    # 가장자리를 부드럽게 — 계단 현상 줄이기
    alpha = np.array(Image.fromarray(alpha).filter(ImageFilter.MinFilter(3)).filter(ImageFilter.GaussianBlur(0.8)))

    small = np.array(Image.fromarray(alpha).resize((alpha.shape[1] // SCALE, alpha.shape[0] // SCALE))) > 128
    labels, comps = label_components(small)
    comps.sort(key=lambda c: c["size"], reverse=True)
    bodies, extras = comps[:len(POSES)], [c for c in comps[len(POSES):] if c["size"] >= 3]

    # 위 줄 / 아래 줄, 그 안에서 왼쪽부터
    mid_y = small.shape[0] / 2
    bodies.sort(key=lambda c: ((c["box"][1] + c["box"][3]) / 2 > mid_y, c["box"][0]))
    groups = {c["id"]: [c["id"]] for c in bodies}
    can_take = [c for name, c in zip(POSES, bodies) if name not in NO_EXTRAS]
    for extra in extras:
        nearest = min(can_take, key=lambda c: box_distance(c["box"], extra["box"]))
        groups[nearest["id"]].append(extra["id"])

    full_labels = np.repeat(np.repeat(labels, SCALE, axis=0), SCALE, axis=1)
    full_labels = np.pad(full_labels, ((0, alpha.shape[0] - full_labels.shape[0]), (0, alpha.shape[1] - full_labels.shape[1])))
    for name, body in zip(POSES, bodies):
        mine = np.isin(full_labels, groups[body["id"]])
        # 1/4 크기 경계에서 잘린 가장자리를 살리려고 소속 영역을 조금 넓힌다
        mine = np.array(Image.fromarray(mine.astype(np.uint8) * 255).filter(ImageFilter.MaxFilter(9))) > 0
        piece = Image.fromarray(np.dstack([rgb, np.where(mine, alpha, 0).astype(np.uint8)]), "RGBA")
        piece = piece.crop(piece.getbbox())
        side = max(piece.size) + 16
        canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
        canvas.paste(piece, ((side - piece.width) // 2, side - piece.height - 8), piece)
        canvas.save(OUT_DIR / f"{name}.png")
        print(f"{name:10} {canvas.size}  장식 {len(groups[body['id']]) - 1}개")


def make_avatar(source: str = "wave", size: int = 256) -> None:
    """채팅 말풍선용 얼굴 아바타 — 전신은 작게 줄이면 알아보기 어렵다."""
    im = Image.open(OUT_DIR / f"{source}.png")
    im = im.crop(im.getbbox())
    alpha = np.array(im)[..., 3] > 128
    # 머리 = 위에서 45% 안쪽의 가로 폭을 한 변으로 하는 정사각형
    rows = np.nonzero(alpha.any(axis=1))[0]
    top = rows[0]
    head_cols = np.nonzero(alpha[top: top + int(im.height * 0.45)].any(axis=0))[0]
    left, right = head_cols[0], head_cols[-1]
    side = right - left
    box = (left - side // 12, top - side // 12, right + side // 12, top + side + side // 12)
    face = im.crop(box).resize((size, size), Image.LANCZOS)
    face.save(OUT_DIR / "avatar.png")
    print(f"avatar     {face.size}")


if __name__ == "__main__":
    main()
    make_avatar()
