"""페이지 주소 QR 코드 만들기 (주소가 바뀔 때만 실행).

실행: python scripts/make_qr.py
결과: docs/qr.svg (화면용, 확대해도 선명), docs/qr.png (인쇄·메신저 공유용)
"""
from pathlib import Path

import qrcode
import qrcode.image.svg

URL = "https://makecore.github.io/lunch/"
DOCS = Path(__file__).resolve().parent.parent / "docs"


def make(factory=None):
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, border=2, box_size=24,
                       image_factory=factory)
    qr.add_data(URL)
    qr.make(fit=True)
    return qr


make(qrcode.image.svg.SvgPathImage).make_image().save(DOCS / "qr.svg")
make().make_image(fill_color="#174c3c", back_color="white").save(DOCS / "qr.png")
print("QR 코드 생성:", URL)
