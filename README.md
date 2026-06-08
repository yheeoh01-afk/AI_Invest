# AI 투자비서 V9.1 Cloud Final

Streamlit Cloud 배포용 최종본입니다.

## 필수 파일
- app.py
- requirements.txt
- runtime.txt
- .streamlit/config.toml

## Streamlit Cloud Secrets
```toml
NAVER_CLIENT_ID = "네이버_API_ID"
NAVER_CLIENT_SECRET = "네이버_API_SECRET"

[USERS]
younghee = "내비밀번호"
sister = "언니비밀번호"
```

## Python 버전
runtime.txt로 python-3.11을 사용하도록 지정했습니다.

## pykrx 오류 보정
Python 3.14 / 최신 setuptools 환경에서 발생하는 pkg_resources 오류 우회 코드를 app.py에 포함했습니다.
