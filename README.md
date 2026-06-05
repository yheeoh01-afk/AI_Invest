# AI 투자비서 V9 Cloud 배포용

## 포함 파일
- app.py
- requirements.txt
- .streamlit/config.toml
- .streamlit/secrets.toml.example

## 배포 순서
1. GitHub에 새 Repository 생성
2. 이 폴더 안의 파일들을 업로드
3. Streamlit Community Cloud에서 Create app
4. Repository 선택
5. Main file path: app.py
6. App settings > Secrets에 아래 형식 입력

```toml
NAVER_CLIENT_ID = "네이버 API ID"
NAVER_CLIENT_SECRET = "네이버 API SECRET"

[USERS]
younghee = "내비밀번호"
sister = "언니비밀번호"
```

## 사용자별 데이터
로그인 사용자별로 아래 파일이 자동 생성됩니다.

- data/younghee_portfolio.csv
- data/younghee_watchlist.csv
- data/sister_portfolio.csv
- data/sister_watchlist.csv

주의: Streamlit Cloud의 로컬 파일 저장은 간단한 가족용 테스트에는 쓸 수 있지만,
앱 재배포/재시작 상황에서 영구 DB처럼 안정적이지 않을 수 있습니다.
장기적으로는 Google Sheets, Supabase, PostgreSQL 같은 외부 DB 연결을 추천합니다.
