# 실적 분석 통계

종합측정실 · 치수 · Hole · 외관 **인력 기준 실적** — 캠퍼스·조·주/야 분석

## 화면 구성

| 페이지 | 설명 |
|--------|------|
| **실적분석통계** (첫 화면) | 캠퍼스·조별 시계열 누적 막대, 주/야 차이 |
| **종합 실적 분석** | 조·주/야·공정 KPI 및 상세 통계 |

## 로컬 실행

```bash
pip install -r requirements.txt
python 실적분석통계.py
```

또는 `run_app.bat` — 브라우저 `http://localhost:8502`

사이드바 **프로그램 종료**로 서버를 끌 수 있습니다.

## 로그인 / 회원가입

앱을 열려면 **로그인**이 필요합니다. (드릴 파손 카운트와 동일)

1. `.streamlit/secrets.toml.example` → `.streamlit/secrets.toml` 복사 (로컬)
2. Streamlit Cloud → App settings → **Secrets**에 동일 내용

### GitHub에 계정 유지 (Cloud 권장)

```toml
[auth]
admin_username = "admin"
admin_password = "change-me-strong-password"

[github]
token = "발급한_토큰"
repo = "계정명/저장소명"
path = "data/users.json"
branch = "main"
```

- 토큰: Fine-grained → Repository access + **Contents: Read and write**
- 첫 가입자 = 관리자 / 비밀번호는 해시만 저장

## GitHub 업로드

1. [GitHub](https://github.com/new)에서 새 저장소 생성 (예: `performance-stats`)
2. 이 폴더에서:

```bash
cd "20260826 실적 분석 통계"
git init -b main
git add .
git commit -m "실적 분석 통계 초기 배포"
git remote add origin https://github.com/<계정>/<저장소>.git
git push -u origin main
```

> `data/` 안의 엑셀·CSV는 `.gitignore`로 제외됩니다. Cloud에서는 업로드로 사용합니다.

## Streamlit Cloud 배포 (공유)

1. [share.streamlit.io](https://share.streamlit.io) 로그인 (GitHub 연동)
2. **New app**
3. Repository: 위 GitHub 저장소 선택
4. **Main file path:** `실적분석통계.py`
5. **Deploy**
6. 생성된 URL(예: `https://xxx.streamlit.app`)을 필요한 분에게 공유

### Cloud 사용 시

- 재시작 시 `data/`가 비워질 수 있음 → 사이드바 **엑셀/CSV 업로드** 또는 **기본 CSV 양식** 사용
- 앱은 **Private**로 두고, Streamlit Cloud에서 Viewer 초대 가능

## CSV 양식 (K·L열)

| 열 | 내용 |
|----|------|
| A~J | 일자, 조, 공정별 인력/실적 |
| K | 캠퍼스 (천안 / 아산) |
| L | 주야 (주 / 야) |

## 로컬 데이터 (선택)

```text
\\192.168.5.2\...\Y26Q1.xlsx  →  data\Y26Q1.xlsx
```

`copy_source_excel.bat` 참고
