"""
tour_lookup_api.py — tourfiremai Tour Lookup API
==================================================
FastAPI server สำหรับให้ Make.com เรียกดึงข้อมูลทัวร์จาก tourfiremai.com
รวมถึงดาวน์โหลด + อ่าน PDF แบบ real-time ก่อนส่งให้ Claude

การติดตั้ง:
    pip install fastapi uvicorn httpx pdfplumber pytesseract pdf2image --break-system-packages

การรัน (local):
    uvicorn tour_lookup_api:app --host 0.0.0.0 --port 8000 --reload

การ Deploy (แนะนำ Railway.app หรือ Render.com — ฟรี):
    1. Push โค้ดขึ้น GitHub
    2. Connect Railway/Render → Deploy อัตโนมัติ
    3. ได้ URL เช่น https://tourfiremai-api.railway.app

Make.com เรียกได้ที่:
    POST https://your-api.railway.app/lookup
    Body: {"keyword": "ญี่ปุ่น", "program_name": "TOKYO JAPAN ALPS"}
"""

import re
import asyncio
import logging
from typing import Optional

import httpx
import pdfplumber
from io import BytesIO
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# ── OCR fallback (optional) ──────────────────────────────────────────────
try:
    from pdf2image import convert_from_bytes
    import pytesseract
    HAS_OCR = True
except ImportError:
    HAS_OCR = False

# ════════════════════════════════════════════════════════════════════════════
# Config
# ════════════════════════════════════════════════════════════════════════════

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Country ID map (จาก tourfiremai.com) — ครบ 66 ประเทศ
COUNTRY_MAP = {
    # เอเชียตะวันออก
    "เกาหลี": 1, "korea": 1,
    "ญี่ปุ่น": 2, "japan": 2,
    "ฮ่องกง": 3, "hongkong": 3, "hong kong": 3,
    "จีน": 5, "china": 5,
    "ไต้หวัน": 19, "taiwan": 19,
    "มาเก๊า": 29, "macau": 29, "macao": 29,
    # เอเชียตะวันออกเฉียงใต้
    "สิงคโปร์": 4, "singapore": 4,
    "มาเลเซีย": 6, "malaysia": 6,
    "เวียดนาม": 7, "vietnam": 7,
    "พม่า": 8, "myanmar": 8, "burma": 8,
    "ลาว": 9, "laos": 9,
    "อินโดนีเซีย": 18, "indonesia": 18,
    "ฟิลิปปินส์": 104, "philippines": 104,
    # เอเชียใต้
    "อินเดีย": 14, "india": 14,
    "ภูฏาน": 20, "bhutan": 20,
    "ศรีลังกา": 182, "srilanka": 182, "sri lanka": 182,
    # เอเชียกลาง/คอเคซัส
    "คาซัคสถาน": 256, "kazakhstan": 256,
    "อุซเบกิสถาน": 173, "uzbekistan": 173,
    "จอร์เจีย": 168, "georgia": 168,
    "คีร์กีซสถาน": 257, "kyrgyzstan": 257,
    "ทิเบต": 184, "tibet": 184,
    # เอเชียตะวันออกกลาง
    "อียิปต์": 16, "egypt": 16,
    "จอร์แดน": 70, "jordan": 70,
    "สหรัฐอาหรับฯ": 72, "uae": 72, "dubai": 72, "ดูไบ": 72,
    "อิหร่าน": 183, "iran": 183,
    # โอเชียเนีย
    "ออสเตรเลีย": 10, "australia": 10,
    "นิวซีแลนด์": 11, "newzealand": 11, "new zealand": 11,
    # อเมริกาเหนือ
    "อเมริกา": 12, "usa": 12, "america": 12,
    "แคนาดา": 73, "canada": 73,
    "เม็กซิโก": 272, "mexico": 272,
    # อเมริกาใต้
    "บราซิล": 174, "brazil": 174,
    "อาร์เจนติน่า": 175, "argentina": 175,
    "โคลอมเบีย": 226, "colombia": 226,
    # ยุโรปตะวันตก
    "สวิตเซอร์แลนด์": 64, "switzerland": 64,
    "เยอรมนี": 100, "germany": 100,
    "ฝรั่งเศส": 101, "france": 101,
    "อิตาลี": 102, "italy": 102,
    "สเปน": 105, "spain": 105,
    "ออสเตรีย": 159, "austria": 159,
    "โปรตุเกส": 200, "portugal": 200,
    "เนเธอร์แลนด์": 308, "netherlands": 308, "holland": 308,
    "เบลเยี่ยม": 213, "belgium": 213,
    "เบเนลักซ์": 2217, "benelux": 2217,
    # ยุโรปเหนือ
    "ฟินแลนด์": 65, "finland": 65,
    "สแกนดิเนเวีย": 47, "scandinavia": 47,
    "นอร์เวย์": 162, "norway": 162,
    "สวีเดน": 153, "sweden": 153,
    "เดนมาร์ก": 232, "denmark": 232,
    "ไอซ์แลนด์": 25, "iceland": 25,
    "ไอร์แลนด์": 194, "ireland": 194,
    "สกอตแลนด์": 197, "scotland": 197,
    "อังกฤษ": 42, "england": 42, "uk": 42,
    "มอลตา": 275, "malta": 275,
    "หมู่เกาะแฟโร": 2275, "faroe": 2275,
    # ยุโรปตะวันออก
    "รัสเซีย": 17, "russia": 17,
    "ยุโรปตะวันออก": 80, "eastern europe": 80,
    "โปแลนด์": 166, "poland": 166,
    "โครเอเชีย": 66, "croatia": 66,
    "โรมาเนีย": 2220, "romania": 2220,
    "มอนเตเนโกร": 276, "montenegro": 276,
    "บอลติก": 2213, "baltic": 2213,
    "กรีซ": 169, "greece": 169,
    "ตุรเคีย": 71, "turkey": 71, "ตุรกี": 71,
    # แอฟริกา
    "แอฟริกาใต้": 68, "south africa": 68,
    "เคนย่า": 167, "kenya": 167,
    "โมร็อกโก": 161, "morocco": 161,
}

# Thai name suffix for listing URL — required by tourfiremai.com
# URL pattern: /intertour/{id}/{thai_name}
COUNTRY_NAMES = {
    1:   "ทัวร์เกาหลี",
    2:   "ทัวร์ญี่ปุ่น",
    3:   "ทัวร์ฮ่องกง",
    4:   "ทัวร์สิงคโปร์",
    5:   "ทัวร์จีน",
    6:   "ทัวร์มาเลเซีย",
    7:   "ทัวร์เวียดนาม",
    8:   "ทัวร์พม่า",
    9:   "ทัวร์ลาว",
    10:  "ทัวร์ออสเตรเลีย",
    11:  "ทัวร์นิวซีแลนด์",
    12:  "ทัวร์อเมริกา",
    14:  "ทัวร์อินเดีย",
    16:  "ทัวร์อียิปต์",
    17:  "ทัวร์รัสเซีย",
    18:  "ทัวร์อินโดนีเซีย",
    19:  "ทัวร์ไต้หวัน",
    20:  "ทัวร์ภูฏาน",
    25:  "ทัวร์ไอซ์แลนด์",
    29:  "ทัวร์มาเก๊า",
    42:  "ทัวร์อังกฤษ",
    47:  "ทัวร์สแกนดิเนเวีย",
    64:  "ทัวร์สวิตเซอร์แลนด์",
    65:  "ทัวร์ฟินแลนด์",
    66:  "ทัวร์โครเอเชีย",
    68:  "ทัวร์แอฟริกาใต้",
    70:  "ทัวร์จอร์แดน",
    71:  "ทัวร์ตุรเคีย",
    72:  "ทัวร์สหรัฐอาหรับฯ",
    73:  "ทัวร์แคนาดา",
    80:  "ทัวร์ยุโรปตะวันออก",
    100: "ทัวร์เยอรมนี",
    101: "ทัวร์ฝรั่งเศส",
    102: "ทัวร์อิตาลี",
    104: "ทัวร์ฟิลิปปินส์",
    105: "ทัวร์สเปน",
    153: "ทัวร์สวีเดน",
    159: "ทัวร์ออสเตรีย",
    161: "ทัวร์โมร็อกโก",
    162: "ทัวร์นอร์เวย์",
    166: "ทัวร์โปแลนด์",
    167: "ทัวร์เคนย่า",
    168: "ทัวร์จอร์เจีย",
    169: "ทัวร์กรีซ",
    173: "ทัวร์อุซเบกิสถาน",
    174: "ทัวร์บราซิล",
    175: "ทัวร์อาร์เจนติน่า",
    182: "ทัวร์ศรีลังกา",
    183: "ทัวร์อิหร่าน",
    184: "ทัวร์ทิเบต",
    194: "ทัวร์ไอร์แลนด์",
    197: "ทัวร์สกอตแลนด์",
    200: "ทัวร์โปรตุเกส",
    213: "ทัวร์เบลเยี่ยม",
    226: "ทัวร์โคลอมเบีย",
    232: "ทัวร์เดนมาร์ก",
    256: "ทัวร์คาซัคสถาน",
    257: "ทัวร์คีร์กีซสถาน",
    272: "ทัวร์เม็กซิโก",
    275: "ทัวร์มอลตา",
    276: "ทัวร์มอนเตเนโกร",
    308: "ทัวร์เนเธอร์แลนด์",
    2213: "ทัวร์บอลติก",
    2217: "ทัวร์เบเนลักซ์",
    2220: "ทัวร์โรมาเนีย",
    2275: "ทัวร์หมู่เกาะแฟโร",
}

BASE_URL = "https://www.tourfiremai.com"
PDF_URL  = "https://www.tourfiremai.com/programtour/tour_{id}.pdf"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept-Language": "th-TH,th;q=0.9,en;q=0.8",
}

# OCR.space API Key
# ขอฟรีได้ที่ https://ocr.space/ocrapi (25,000 req/เดือน)
# ตั้งเป็น environment variable: OCR_API_KEY=K123...
# ถ้าไม่ตั้ง จะใช้ demo key "helloworld" (rate-limited)
import os
OCR_API_KEY = os.environ.get("OCR_API_KEY", "helloworld")

# ════════════════════════════════════════════════════════════════════════════
# FastAPI App
# ════════════════════════════════════════════════════════════════════════════

app = FastAPI(
    title="tourfiremai Tour Lookup API",
    description="Real-time tour info + PDF extraction for น้องแอดมิน chatbot",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ════════════════════════════════════════════════════════════════════════════
# Request / Response models
# ════════════════════════════════════════════════════════════════════════════

class LookupRequest(BaseModel):
    keyword: str                        # เช่น "ญี่ปุ่น", "เกาหลี 5 วัน"
    program_name: Optional[str] = None  # เช่น "TOKYO JAPAN ALPS" (ถ้ารู้)
    max_programs: int = 2               # จำนวนโปรแกรมที่ต้องการ (max 3)

class ProgramInfo(BaseModel):
    tour_id: str
    program_name: str
    price_start: Optional[str]
    travel_dates: list[str]
    pdf_url: str
    pdf_text: str           # full text จาก PDF
    pdf_summary: str        # สรุปสั้น: ราคา ทิป มัดจำ เงื่อนไข
    source_url: str


# ════════════════════════════════════════════════════════════════════════════
# Core functions
# ════════════════════════════════════════════════════════════════════════════

def detect_country_id(keyword: str) -> Optional[int]:
    """หา country ID จาก keyword"""
    kw = keyword.lower().strip()
    for k, v in COUNTRY_MAP.items():
        if k in kw:
            return v
    return None


async def fetch_tour_ids(keyword: str, client: httpx.AsyncClient) -> list[str]:
    """ดึง Tour IDs จากหน้า listing ของ tourfiremai

    URL ที่ถูกต้อง: /intertour/{id}/{thai_name}  เช่น /intertour/2/ทัวร์ญี่ปุ่น
    หากไม่รู้ประเทศ → fallback ค้นผ่าน /search
    """
    country_id = detect_country_id(keyword)

    if country_id and country_id in COUNTRY_NAMES:
        thai_name = COUNTRY_NAMES[country_id]
        url = f"{BASE_URL}/intertour/{country_id}/{thai_name}"
    elif country_id:
        # มี ID แต่ไม่มีชื่อไทย → ลองใช้ ID อย่างเดียวก่อน
        url = f"{BASE_URL}/intertour/{country_id}"
    else:
        # fallback: search ด้วย keyword
        url = f"{BASE_URL}/search?keyword={keyword}"

    logger.info(f"fetch_tour_ids → {url}")

    try:
        resp = await client.get(url, headers=HEADERS, timeout=15,
                                follow_redirects=True)
        html = resp.text
        ids = re.findall(r'/tour/(ap\d+)', html)
        # deduplicate, preserve order
        seen = set()
        unique = []
        for i in ids:
            if i not in seen:
                seen.add(i)
                unique.append(i)
        logger.info(f"found {len(unique)} tour IDs")
        return unique
    except Exception as e:
        logger.error(f"fetch_tour_ids error: {e}")
        return []


async def fetch_tour_html_info(tour_id: str, client: httpx.AsyncClient) -> dict:
    """ดึงข้อมูลพื้นฐานจากหน้า HTML ของโปรแกรม"""
    url = f"{BASE_URL}/tour/{tour_id}"
    info = {
        "tour_id": tour_id,
        "program_name": "",
        "price_start": None,
        "travel_dates": [],
        "source_url": url,
    }
    try:
        resp = await client.get(url, headers=HEADERS, timeout=15)
        html = resp.text

        # ชื่อโปรแกรม
        m = re.search(r'<h1[^>]*class="t-name2"[^>]*>(.*?)</h1>', html, re.DOTALL)
        if m:
            info["program_name"] = re.sub(r'<[^>]+>', '', m.group(1)).strip()

        # ราคาเริ่มต้น
        m = re.search(r'class="price-dtn">([\d,]+)<', html)
        if m:
            info["price_start"] = m.group(1).strip() + " บาท/ท่าน"

        # วันเดินทาง
        dates = re.findall(r'(\d{1,2}\s+(?:ม\.ค\.|ก\.พ\.|มี\.ค\.|เม\.ย\.|พ\.ค\.|มิ\.ย\.|ก\.ค\.|ส\.ค\.|ก\.ย\.|ต\.ค\.|พ\.ย\.|ธ\.ค\.)\s+\d{2})', html)
        info["travel_dates"] = list(dict.fromkeys(dates))[:6]

    except Exception as e:
        logger.error(f"fetch_tour_html_info error for {tour_id}: {e}")

    return info


def extract_pdf_text(pdf_bytes: bytes) -> str:
    """อ่าน text จาก PDF bytes — ลอง pdfplumber ก่อน fallback Tesseract OCR

    หมายเหตุ: tourfiremai PDFs เป็น scanned images ทั้งหมด
    → pdfplumber จะได้ text ว่าง → ต้องใช้ OCR เสมอ
    → ใน production ใช้ฟังก์ชัน extract_pdf_text_via_ocrspace() แทน
    """
    text = ""

    # ── วิธี 1: pdfplumber (PDF ที่มี text layer) ───────────────────────
    try:
        with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages:
                t = page.extract_text()
                if t:
                    text += t + "\n"
    except Exception as e:
        logger.warning(f"pdfplumber failed: {e}")

    # ── วิธี 2: Tesseract OCR (ต้องติดตั้ง tesseract-ocr-tha บนเซิร์ฟเวอร์) ──
    if len(text.strip()) < 100 and HAS_OCR:
        logger.info("Text layer empty → switching to Tesseract OCR...")
        try:
            images = convert_from_bytes(pdf_bytes, dpi=200)
            for img in images[:6]:   # จำกัด 6 หน้าแรก (ข้อมูลราคาอยู่ต้น PDF)
                text += pytesseract.image_to_string(img, lang="tha+eng")
        except Exception as e:
            logger.warning(f"Tesseract OCR failed: {e}")

    return text.strip()


async def extract_pdf_text_via_ocrspace(pdf_url: str, client: httpx.AsyncClient,
                                         ocr_api_key: str = "helloworld") -> str:
    """OCR ผ่าน OCR.space API — ใช้สำหรับ production บน Railway/Render

    ข้อดี:
    - ไม่ต้องติดตั้ง Tesseract + Thai lang pack บนเซิร์ฟเวอร์
    - รองรับภาษาไทยดีมาก
    - Free tier: 25,000 requests/เดือน

    การขอ API Key ฟรี: https://ocr.space/ocrapi
    หากใช้ key "helloworld" จะมี rate limit เข้มขึ้น

    Args:
        pdf_url: URL ตรงไปยัง PDF เช่น https://www.tourfiremai.com/programtour/tour_242560.pdf
        ocr_api_key: API key จาก ocr.space (default: demo key "helloworld")
    """
    try:
        payload = {
            "apikey":    ocr_api_key,
            "url":       pdf_url,
            "language":  "tha",
            "isTable":   "true",
            "scale":     "true",
            "OCREngine": "2",          # Engine 2 ดีกว่าสำหรับภาษาไทย
        }
        resp = await client.post(
            "https://api.ocr.space/parse/image",
            data=payload,
            timeout=60,
        )
        data = resp.json()

        if data.get("IsErroredOnProcessing"):
            logger.warning(f"OCR.space error: {data.get('ErrorMessage')}")
            return ""

        pages = data.get("ParsedResults", [])
        return "\n".join(p.get("ParsedText", "") for p in pages).strip()

    except Exception as e:
        logger.error(f"OCR.space failed: {e}")
        return ""


def summarize_pdf(text: str) -> str:
    """สกัดข้อมูลสำคัญจาก PDF text ให้กระชับ สำหรับส่งให้ Claude

    ลำดับความสำคัญ:
    1. ค่าทิปไกด์ / คนขับ / หัวหน้าทัวร์
    2. ค่ามัดจำ + กำหนดชำระยอดเต็ม
    3. ตารางราคาตามวันเดินทาง
    4. รวม/ไม่รวมในราคา
    5. เงื่อนไขยกเลิก
    """
    if not text:
        return "ไม่สามารถอ่าน PDF ได้"

    # ล้าง CID artifacts ที่เกิดจาก font encoding
    clean = re.sub(r'\(cid:\d+\)', '', text)
    lines = [l.strip() for l in clean.split('\n') if l.strip()]

    important = []

    # Priority keywords — ข้อมูลที่ Claude ต้องการมากที่สุด
    # รวม variants ที่เกิดจาก pdfplumber font-encoding artifacts เช่น:
    #   มัดจำ → มดั จาํ   ชำระ → ชาํ ระ   ทิป → ทปิ   ทริป → ทรปิ
    priority_keywords = [
        'ทิป', 'ทปิ',                    # tip (normal & garbled)
        'tip',
        'มัดจำ', 'มดั จาํ', 'มดั จํา',  # deposit (normal & garbled)
        'deposit',
        'ชำระ', 'ชาํ ระ', 'ชาํ ระ',    # payment (normal & garbled)
        'payment', 'กำหนดชำระ',
        '22,000', '15,000', '10,000',   # common deposit amounts
    ]

    # Secondary keywords
    secondary_keywords = [
        'ราคา', 'ผู้ใหญ่', 'ผใู้ หญ',   # adult price
        'เด็ก', 'พักเดี่ยว', 'single',
        'รวม', 'ไม่รวม', 'include', 'exclude',
        'ยกเลิก', 'cancel', 'refund',
        'วีซ่า', 'visa', 'ตั๋ว', 'โรงแรม',
        'บาท', 'thb',
    ]

    priority_lines = []
    secondary_lines = []

    for line in lines:
        low = line.lower()
        if any(kw in low for kw in priority_keywords):
            priority_lines.append(line)
        elif any(kw in low for kw in secondary_keywords):
            secondary_lines.append(line)

    # รวม priority ก่อน แล้วตาม secondary
    important = priority_lines[:20] + secondary_lines[:40]

    if not important:
        # ถ้าหา keyword ไม่เจอ ให้เอา 40 บรรทัดแรก
        important = lines[:40]

    return '\n'.join(important[:60])  # จำกัด 60 บรรทัด


async def fetch_pdf(tour_id: str, client: httpx.AsyncClient,
                   ocr_api_key: str = "helloworld") -> tuple[str, str]:
    """ดาวน์โหลด PDF และ return (full_text, summary)

    Strategy:
    1. ดาวน์โหลด PDF → ลอง pdfplumber ก่อน (เร็ว)
    2. ถ้าได้ text น้อยกว่า 100 chars (= scanned PDF) → ใช้ OCR.space API
    3. ถ้า OCR.space ไม่สำเร็จ → fallback Tesseract ถ้าติดตั้งไว้
    """
    numeric_id = tour_id.replace("ap", "")
    url = PDF_URL.format(id=numeric_id)

    try:
        resp = await client.get(url, headers=HEADERS, timeout=30,
                                follow_redirects=True)
        if resp.status_code != 200:
            return "", f"PDF ไม่พบ (HTTP {resp.status_code})"

        pdf_bytes = resp.content

        # ── Step 1: pdfplumber ──────────────────────────────────────────
        full_text = extract_pdf_text(pdf_bytes)

        # ── Step 2: OCR.space (ถ้า pdfplumber ได้น้อยเกินไป) ────────────
        if len(full_text.strip()) < 100:
            logger.info(f"pdfplumber got <100 chars for {tour_id} → using OCR.space")
            full_text = await extract_pdf_text_via_ocrspace(url, client, ocr_api_key)

        summary = summarize_pdf(full_text)
        return full_text, summary

    except Exception as e:
        logger.error(f"fetch_pdf error for {tour_id}: {e}")
        return "", f"ดึง PDF ไม่สำเร็จ: {str(e)}"


# ════════════════════════════════════════════════════════════════════════════
# API Endpoints
# ════════════════════════════════════════════════════════════════════════════

class LookupRequest(BaseModel):
    keyword: str
    max_programs: int = 2


class ProgramResult(BaseModel):
    tour_id: str
    program_name: str
    price_start: Optional[str] = None
    travel_dates: list[str]
    pdf_url: str
    pdf_text: str
    pdf_summary: str
    source_url: str


@app.get("/")
async def root():
    return {
        "api": "tourfiremai Tour Lookup API",
        "version": "1.1.0",
        "countries_supported": len(COUNTRY_NAMES),
        "endpoints": {
            "POST /lookup": "ค้นหาทัวร์จาก keyword + ดึง PDF",
            "GET /program/{tour_id}": "ดึงโปรแกรมเดี่ยว เช่น /program/ap242560",
            "GET /health": "Health check",
        }
    }


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "ocr_key_set": OCR_API_KEY != "helloworld",
        "tesseract_available": HAS_OCR,
        "countries_supported": len(COUNTRY_NAMES),
    }


@app.post("/lookup", response_model=list[ProgramResult])
async def lookup(req: LookupRequest):
    """ค้นหาทัวร์จาก keyword และดึง PDF ข้อมูลแบบ real-time"""
    async with httpx.AsyncClient() as client:
        tour_ids = await fetch_tour_ids(req.keyword, client)
        if not tour_ids:
            raise HTTPException(status_code=404, detail=f"ไม่พบทัวร์สำหรับ '{req.keyword}'")

        tour_ids = tour_ids[:req.max_programs]

        results = []
        for tid in tour_ids:
            info = await fetch_tour_html_info(tid, client)
            pdf_text, pdf_summary = await fetch_pdf(tid, client, OCR_API_KEY)
            results.append(ProgramResult(
                tour_id=tid,
                program_name=info.get("program_name", ""),
                price_start=info.get("price_start") or None,
                travel_dates=info.get("travel_dates", []),
                pdf_url=PDF_URL.format(id=tid.replace("ap", "")),
                pdf_text=pdf_text[:4000],
                pdf_summary=pdf_summary,
                source_url=f"{BASE_URL}/tour/{tid}",
            ))

        return results


@app.get("/program/{tour_id}", response_model=ProgramResult)
async def get_program(tour_id: str):
    """ดึงข้อมูลโปรแกรมเดี่ยวพร้อม PDF"""
    async with httpx.AsyncClient() as client:
        info = await fetch_tour_html_info(tour_id, client)
        pdf_text, pdf_summary = await fetch_pdf(tour_id, client, OCR_API_KEY)
        return ProgramResult(
            tour_id=tour_id,
            program_name=info.get("program_name", ""),
            price_start=info.get("price_start", ""),
            travel_dates=info.get("travel_dates", []),
            pdf_url=PDF_URL.format(id=tour_id.replace("ap", "")),
            pdf_text=pdf_text[:4000],
            pdf_summary=pdf_summary,
            source_url=f"{BASE_URL}/tour/{tour_id}",
        )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("tour_lookup_api:app", host="0.0.0.0", port=int(os.environ.get("PORT", 8000)), reload=True)
