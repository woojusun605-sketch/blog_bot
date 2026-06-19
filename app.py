import io
import time
import zipfile
import datetime
import streamlit as st
from google import genai
from PIL import Image

# ==========================================
# 🌟 설정 (비밀값은 코드가 아니라 secrets에서 읽어옵니다)
# ==========================================
def get_secret(name, default=""):
    try:
        return st.secrets[name]
    except Exception:
        return default

GEMINI_API_KEY = get_secret("GEMINI_API_KEY")
APP_PASSWORD = get_secret("APP_PASSWORD")

# 사용할 모델 
MODEL_NAME = "gemini-2.5-flash"

st.set_page_config(page_title="제로맥스 블로그 AI", page_icon="🚗", layout="wide")


# ==========================================
# 🔒 비밀번호 게이트
# ==========================================
def check_password():
    """공용 비밀번호가 맞아야 통과. 비밀번호는 secrets에 보관."""
    if st.session_state.get("password_ok", False):
        return True

    def _verify():
        if APP_PASSWORD and st.session_state.get("password_input") == APP_PASSWORD:
            st.session_state["password_ok"] = True
            st.session_state.pop("password_input", None)
        else:
            st.session_state["password_ok"] = False

    st.title("🔒 부천 제로맥스 블로그 AI")
    st.caption("사내 공용 도구입니다. 접속 비밀번호를 입력해 주세요.")

    if not APP_PASSWORD:
        st.error("관리자 설정 필요: Secrets 에 APP_PASSWORD 가 설정되지 않았습니다.")
        return False

    st.text_input("비밀번호", type="password", key="password_input", on_change=_verify)
    if "password_ok" in st.session_state and not st.session_state["password_ok"]:
        st.error("비밀번호가 올바르지 않습니다.")
    return False


if not check_password():
    st.stop()


# ==========================================
# 🌟 도구 함수
# ==========================================
def prepare_image_for_api(pil_image):
    """AI 분석용 이미지 최적화 (토큰 절약 및 속도를 위해 768px 제한)"""
    max_size = 768  
    width, height = pil_image.size
    if width > max_size or height > max_size:
        ratio = min(max_size / width, max_size / height)
        new_size = (int(width * ratio), int(height * ratio))
        return pil_image.resize(new_size, Image.Resampling.LANCZOS)
    return pil_image

def resize_for_blog(pil_image, max_width=960):
    """네이버 블로그 업로드용 이미지 최적화 (가로 960px 맞춤)"""
    width, height = pil_image.size
    if width > max_width:
        ratio = max_width / width
        new_size = (int(width * ratio), int(height * ratio))
        return pil_image.resize(new_size, Image.Resampling.LANCZOS)
    return pil_image

def generate_with_retry(client, model, contents, max_retries=4):
    """일시적 오류(503 과부하, 429 한도 등)면 잠시 쉬었다가 자동 재시도."""
    delay = 2
    last_err = None
    for attempt in range(max_retries):
        try:
            return client.models.generate_content(model=model, contents=contents)
        except Exception as e:
            last_err = e
            msg = str(e)
            transient = any(
                k in msg
                for k in ["503", "UNAVAILABLE", "overloaded", "429", "RESOURCE_EXHAUSTED", "500", "INTERNAL"]
            )
            if transient and attempt < max_retries - 1:
                time.sleep(delay)
                delay *= 2
                continue
            raise
    raise last_err

def build_export_zip(text, images):
    """생성된 글(.txt)과 사진들을 ZIP 하나로 묶어 bytes 반환."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("블로그_본문.txt", text.encode("utf-8"))
        for idx, (name, data) in enumerate(images, start=1):
            zf.writestr(f"사진_{idx:02d}_{name}", data)
    return buffer.getvalue()


# ==========================================
# 🌟 메인 화면
# ==========================================
st.title("🚗 부천 제로맥스 블로그 에이전트")
st.caption("차량 정보와 사진을 넣으면, 네이버 검색에 최적화된 제로맥스 디테일링 전문가형 포스팅을 작성해 줍니다.")
st.markdown("---")

st.subheader("🚗 시공 차량 및 작업 설정")

col_car, col_service = st.columns(2)
with col_car:
    car_info = st.text_input("🚙 차량 정보 (필수)", placeholder="예: BMW 520i / 쏘렌토 MQ4 / 포르쉐 911")
with col_service:
    service_type = st.selectbox(
        "🛠️ 시공 항목 선택",
        ("PPF", "썬팅(틴팅)", "광택", "신차패키지", "기타 (직접 입력)")
    )

if service_type == "기타 (직접 입력)":
    custom_service = st.text_input("💡 구체적인 시공명을 적어주세요", placeholder="예: 하이엔드 유리막 코팅, 실내 가죽 코팅 등")
else:
    custom_service = service_type

st.subheader("📝 검색 노출 키워드 설정")

col1, col2 = st.columns(2)
with col1:
    main_keyword = st.text_input("🔑 메인 키워드 (필수)", placeholder="예: 부천 PPF, 인천 신차패키지")
with col2:
    sub_keyword = st.text_input("🏷️ 서브 키워드 (선택)", placeholder="예: 무황변, 스월마크 제거")

user_topic = st.text_area(
    "📝 이번 시공의 특이사항이나 강조할 점 (선택)",
    placeholder="예: 차주분이 야간 운전이 많아 루마 버텍스 밝은 농도로 세팅함 / 앞범퍼 스톤칩 오염이 심했음",
    height=80,
)

uploaded_files = st.file_uploader(
    "이미지 추가 (최대 30장)",
    type=["jpg", "jpeg", "png"],
    accept_multiple_files=True,
)

if uploaded_files:
    if len(uploaded_files) > 30:
        st.warning("사진은 최대 30장까지만 분석됩니다.")
        uploaded_files = uploaded_files[:30]

    for row_start in range(0, len(uploaded_files), 5):
        row_files = uploaded_files[row_start:row_start + 5]
        cols = st.columns(len(row_files))
        for col, file in zip(cols, row_files):
            with col:
                file.seek(0)
                st.image(Image.open(file), caption=file.name, use_container_width=True)

st.markdown("---")

if st.button("✨ 네이버 최적화 블로그 글 생성", type="primary", use_container_width=True):
    if not GEMINI_API_KEY:
        st.error("관리자 설정 필요: Secrets 에 GEMINI_API_KEY 가 설정되지 않았습니다.")
    elif not car_info:
        st.warning("🚙 차량 정보를 입력해 주세요. (필수)")
    elif not main_keyword:
        st.warning("🔑 메인 키워드를 입력해 주세요. (필수)")
    else:
        with st.spinner("제로맥스 디테일링 장인 톤으로 포스팅을 작성 중입니다... (최대 1~2분 소요)"):
            try:
                client = genai.Client(api_key=GEMINI_API_KEY)
                
                # 시공 항목에 따른 최종 시공명 확정
                final_service_name = custom_service if custom_service else "프리미엄 디테일링 시공"

                # 선택한 시공에 따라 프롬프트에 추가할 전문 용어 및 브랜드 가이드 세팅
                service_guides = {
                    "PPF": "PPF 시공 시 프리미엄 필름(예: 엑스펠, 카바차, 스텍 등 최고급 저황변/무황변 TPU 필름)의 뛰어난 방오성과 스크래치 셀프 힐링(자가복원) 기능을 전문가 시각에서 풀어주세요. 컴퓨터 재단과 손재단의 장점만을 결합한 맞춤 시공, 그리고 도장면 안쪽으로 말아 넣는 '엣지 쉐이빙' 마감으로 이질감 없는 완벽한 핏팅 퀄리티를 상세히 설명해 줘.",
                    "썬팅(틴팅)": "썬팅 시공 시 루마 버텍스, 브이쿨, 존슨 등 프리미엄 틴팅 브랜드의 특장점(비금속/금속 필름의 차이, 높은 TSER 총태양에너지차단율, 맑은 시인성)을 고객이 이해하기 쉽게 설명해 주세요. 먼지 유입을 차단하는 연무기 가동 및 풀 마스킹, 필름의 성능 저하를 막는 '세밀한 무터치 열성형(수축)' 노하우를 강조해 줘.",
                    "광택": "광택 시공 시 도장면의 클리어코트(투명층) 삭감을 최소화하면서 광도를 끌어올리는 '듀얼 폴리싱' 기법을 설명해 주세요. 스월마크와 워터스팟의 완벽한 제거, 그리고 틈새에 낀 컴파운드 가루를 제거하는 꼼꼼한 탈지 공정과 세차의 중요성을 어필해 줘.",
                    "신차패키지": "신차패키지 시공 시 매의 눈으로 진행하는 '디테일한 신차 검수(도장 불량, 단차 등)' 과정을 강조하세요. 썬팅+블랙박스+유리막/PPF 등 프리미엄 케미컬과 필름이 결합했을 때의 시너지 효과, 그리고 한 곳에서 완벽하게 끝내는 마스터의 책임 시공을 신뢰감 있게 설명해 줘.",
                    "기타 (직접 입력)": f"이번에 진행된 '{final_service_name}'에 사용되는 최고급 케미컬과 전용 장비의 특장점을 전문적으로 설명하세요. 눈에 보이지 않는 꼼꼼한 전처리 과정부터 완벽한 결과물을 만들어내는 제로맥스만의 타협 없는 디테일링 장인 정신을 강조해 줘."
                }

                selected_guide = service_guides.get(service_type, service_guides["기타 (직접 입력)"])

                prompt = (
                    "당신은 인천·부천 지역 최고의 자동차 프리미엄 토탈 프로샵 '부천 제로맥스(ZEROMAX)'의 대표 디테일러이자 마스터입니다.\n"
                    "부천 제로맥스는 세차부터 시작해 광택, 유리막 코팅, 썬팅, 랩핑, PPF, 신차패키지까지 완벽하게 섭렵한 전문업체입니다.\n"
                    "제공된 작업 사진들과 아래 [작업 정보]를 바탕으로, 네이버 검색 노출(SEO)에 최적화된 신뢰감 있는 전문가형 블로그 포스팅을 작성해 주세요.\n\n"
                    
                    "[작업 정보]\n"
                    f"- 입고 차량: {car_info}\n"
                    f"- 시공 항목: {final_service_name}\n"
                    f"- 메인 키워드: {main_keyword}\n"
                    f"- 서브 키워드: {sub_keyword}\n"
                    f"- 특이사항 및 강조 내용: {user_topic}\n\n"
                    
                    "[톤앤매너 — 매우 중요]\n"
                    "- 차를 진심으로 아끼고 사랑하는 '자동차 디테일링 장인'의 열정과 자부심이 느껴지는 경어체(~합니다, ~입니다)를 사용하세요.\n"
                    "- 가벼운 호들갑(과도한 감탄사, 'ㅎㅎ', 이모지 남발)은 배제하되, 작업의 디테일을 설명할 때는 전문가의 포스가 느껴지도록 무게감 있게 작성하세요.\n\n"
                    
                    "[전문성 가이드 (디테일링 및 시공 포인트)]\n"
                    "1. 차량 기본 정보 소개: 입고된 차량 모델 자체의 디자인 특징이나 제원 등 기본 정보를 서론에 1~2줄 정도로 짧고 자연스럽게 소개해 주세요.\n"
                    "2. 차량 상태 진단: 이어서 입고된 차량의 컨디션(도장면, 오염도, 굴곡 등)을 전문가의 예리한 시선으로 분석하는 내용을 담아주세요.\n"
                    "3. 보이지 않는 정성: 화려한 결과물 이전에 철저한 전처리(세차, 철분/타르 제거, 풀 마스킹, 탈지 등) 과정을 꼼꼼히 묘사해 신뢰를 주세요.\n"
                    f"4. 핵심 기술 및 소재 어필: {selected_guide}\n\n"
                    
                    "[글 분량 — 반드시 지킬 것]\n"
                    "- 본문 설명 글을 공백 포함 약 1,800자 내외(±200자, 즉 1,600~2,000자)로 일관되게 작성하세요.\n"
                    "- 이때 [사진 캡션]과 맨 끝의 #해시태그는 글자 수 계산에서 제외합니다. 순수하게 본문 설명 글만 1,800자 내외로 맞추세요.\n"
                    "- 사진 수가 많아도 각 사진 설명을 간결히 조절해 이 분량을 유지하고, 분량을 채우려고 의미 없는 미사여구를 늘리지 마세요.\n\n"
                    
                    "[네이버 블로그 SEO 규칙 — 반드시 지킬 것]\n"
                    "1. 제목 최적화: 글의 제목은 최상단에 '# 제목: [여기에 제목 작성]' 형태로 출력하되, 25자를 넘지 않게 작성하고 [메인 키워드]를 반드시 문장 맨 앞에 배치하세요.\n"
                    "2. 서론 키워드 배치: 글의 첫 번째 문단 안에 [메인 키워드]와 [서브 키워드]가 자연스럽게 포함되도록 작성하여 검색 로봇이 주제를 빠르게 파악하게 하세요.\n"
                    "3. 모바일 가독성: 스마트폰으로 읽기 편하도록 3~4문장마다 반드시 줄 바꿈을 하고, 명확한 소제목(##)으로 단락을 구분하세요.\n"
                    "4. 사진 캡션(설명) 생성: 본문에 사진을 삽입할 때, 사진 바로 아래에 [사진 캡션: 차량명과 키워드를 포함한 짧은 설명]을 반드시 작성해 주세요. 이는 네이버 이미지 검색 노출에 매우 중요합니다.\n"
                    "5. 해시태그: 글의 맨 마지막에는 네이버 블로그에 바로 복사해 넣을 수 있도록 [메인 키워드]와 [서브 키워드]를 포함한 #해시태그 7~10개를 추천해 주세요.\n\n"
                    
                    "[사진 활용 규칙]\n"
                    "- 업로드된 사진은 '[사진 1]', '[사진 2]' … 순서로 번호와 파일명이 함께 제공됩니다.\n"
                    "- 본문에서 각 사진을 소개할 때 번호와 파일명을 명시하고, 그 아래에 캡션을 달고 이어서 본문을 작성하세요.\n"
                    "- 사진에 실제로 보이는 요소만 묘사하고, 보이지 않는 내용은 지어내지 마세요."
                )

                contents = [prompt]
                export_images = []
                if uploaded_files:
                    for idx, file in enumerate(uploaded_files, start=1):
                        file.seek(0)
                        img = Image.open(file)
                        
                        # 1. AI 분석용 이미지 (768px 축소 - 토큰 및 속도 최적화)
                        api_img = prepare_image_for_api(img.copy())
                        
                        # 2. 블로그 내보내기용 이미지 (가로 960px 맞춤 리사이징 - 용량 최적화)
                        blog_img = resize_for_blog(img.copy(), max_width=960)
                        
                        # 이미지 포맷 및 변환 처리
                        ext = file.name.split('.')[-1].upper()
                        if ext == 'JPG': 
                            ext = 'JPEG'
                        if ext == 'JPEG' and blog_img.mode in ('RGBA', 'P'):
                            blog_img = blog_img.convert('RGB')
                            
                        # 리사이징된 이미지를 bytes로 변환하여 ZIP 저장 목록에 추가
                        img_byte_arr = io.BytesIO()
                        blog_img.save(img_byte_arr, format=ext, quality=90)
                        export_images.append((file.name, img_byte_arr.getvalue()))

                        # 프롬프트에 분석용 이미지 추가
                        contents.append(f"[사진 {idx}] 파일명: {file.name}")
                        contents.append(api_img)

                response = generate_with_retry(client, MODEL_NAME, contents)

                # 결과를 세션에 저장 (다운로드 버튼을 눌러도 사라지지 않도록)
                st.session_state["result_text"] = response.text
                st.session_state["result_images"] = export_images

                # 이번 세션 작업 이력에 추가 (텍스트만 보관 / 새로고침 시 초기화)
                st.session_state.setdefault("history", [])
                st.session_state["hist_counter"] = st.session_state.get("hist_counter", 0) + 1
                st.session_state["history"].insert(0, {
                    "id": st.session_state["hist_counter"],
                    "time": datetime.datetime.now().strftime("%m/%d %H:%M"),
                    "main": main_keyword,
                    "sub": sub_keyword,
                    "text": response.text,
                })
                st.session_state["history"] = st.session_state["history"][:30]  # 너무 쌓이지 않게 30개 제한

            except Exception as e:
                msg = str(e)
                if any(k in msg for k in ["503", "UNAVAILABLE", "overloaded", "429", "RESOURCE_EXHAUSTED"]):
                    st.error("지금 AI 서버 요청이 몰려 일시적으로 응답이 어렵습니다. 잠시 후 생성 버튼을 다시 눌러 주세요. (구글 측 일시 과부하)")
                else:
                    st.error(f"오류가 발생했습니다: {e}")


# ==========================================
# 📋 결과 표시 + 내보내기 
# ==========================================
if st.session_state.get("result_text"):
    st.success("✨ 포스팅 초안이 완성되었습니다!")
    st.markdown("### 📋 생성된 블로그 본문")
    st.text_area(
        "결과물 (복사해서 네이버 블로그에 붙여넣으세요)",
        value=st.session_state["result_text"],
        height=500,
    )

    zip_bytes = build_export_zip(
        st.session_state["result_text"],
        st.session_state.get("result_images", []),
    )
    st.download_button(
        "📦 글 + 블로그용 최적화 사진 한 번에 내보내기 (ZIP)",
        data=zip_bytes,
        file_name="제로맥스_블로그_포스팅.zip",
        mime="application/zip",
        use_container_width=True,
    )
    st.caption("ZIP 안에는 블로그 업로드용으로 최적화(가로 960px)된 사진들이 들어있습니다. 본문의 [사진 N] 순서대로 올려주세요.")


# ==========================================
# 📜 이번 세션 작업 이력 (사이드바 / 텍스트만, 새로고침 시 초기화)
# ==========================================
with st.sidebar:
    st.header("📜 이번 세션 작업 이력")
    history = st.session_state.get("history", [])
    if not history:
        st.caption("아직 생성한 글이 없습니다. 글을 만들면 여기에 쌓입니다.")
    else:
        st.caption("⚠️ 새로고침하거나 다시 접속하면 초기화됩니다.")
        for item in history:
            label = f"{item['time']} · {item['main'] or '(키워드 없음)'}"
            with st.expander(label):
                st.text_area(
                    "본문",
                    value=item["text"],
                    height=200,
                    key=f"hist_{item['id']}",
                )
                fname = "블로그_" + item["time"].replace("/", "").replace(":", "").replace(" ", "_") + ".txt"
                st.download_button(
                    "📄 이 글 .txt로 받기",
                    data=item["text"].encode("utf-8"),
                    file_name=fname,
                    mime="text/plain",
                    key=f"hist_dl_{item['id']}",
                    use_container_width=True,
                )