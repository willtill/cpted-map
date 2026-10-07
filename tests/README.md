# 저장 회귀 검사

Python Playwright와 Chromium이 설치된 환경에서 실행합니다. 브라우저 실행 파일이
`/usr/bin/chromium`이 아니면 `CHROMIUM_PATH`를 지정합니다.

```sh
python3 -m unittest discover -s tests -v
```

실제 ZIP 생성·재읽기 검사까지 실행하려면 JSZip 3.10.1의 배포 파일을 지정합니다.
저장소의 의존성 파일을 변경할 필요는 없습니다.

```sh
curl --fail --location https://cdn.jsdelivr.net/npm/jszip@3.10.1/dist/jszip.min.js -o /tmp/cpted-jszip-3.10.1.js
JSZIP_PATH=/tmp/cpted-jszip-3.10.1.js python3 -m unittest discover -s tests -v
```

검사는 격리된 브라우저 저장소와 공유 API 대역을 사용합니다. 실제 사용자의 기록은
읽거나 변경하지 않습니다. 다음을 확인합니다.

- 파일 준비 후 새 클릭에서만 공유 호출, 취소·권한 오류 후 재시도
- Android 직접 다운로드와 ZIP MIME 타입
- PNG 사진의 실제 JPEG 변환·디코딩 및 XMP 메모 보존
- IndexedDB 커밋과 실패 시 폼/입력 유지
- 중복 파일명 12개와 노트가 빠짐없이 ZIP 한 개로 저장됨
- 아미동·합성동 각각 사진 20개(약 19 MiB), 요소별 최신 노트, 사진 없는 요소의
  노트 및 기존 data URL 사진을 포함하는 ZIP의 내용과 원본 바이트 보존

## iPhone/iPad 실기기 확인

자동 검사는 iOS의 네이티브 공유 화면이나 실제 HEIC 디코더를 대신하지 않습니다.
배포 후 Safari에서 다음을 확인합니다.

1. JPEG·PNG·HEIC 사진과 요소별 노트를 추가하고 새로고침 후 기록이 남아 있는지 확인합니다.
2. 사진 1개와 6개 이상을 각각 내보내고, 준비 화면의 **공유 / 파일에 저장**을
   직접 누릅니다. 여러 항목은 ZIP 한 개로 저장되어야 합니다.
3. 아미동·합성동 일괄 내보내기로 파일 앱에 저장한 ZIP을 풀어 사진 수, 최신 메모,
   사진 없는 요소의 노트와 `전체기록.json`의 사진 연결을 확인합니다.
   지역별 ZIP은 원본 사진 형식을 유지합니다.
4. 공유를 취소했다가 재시도합니다. 취소한 저장을 완료로 표시하거나 기록을
   삭제하면 안 됩니다. 공유를 지원하지 않는 경우 개별 파일 링크로 저장합니다.
