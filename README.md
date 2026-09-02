# KIA Tigers Broadcast Telegram Bot

KBO 공식 Daily Schedule을 확인해 해당년도 KIA 타이거즈 정규시즌 및 포스트시즌 경기 일정, 선발투수, TV 중계 채널, 경기 변동사항을 텔레그램으로 보내는 GitHub Actions 기반 봇입니다.

- 공식 일정 출처: <https://eng.koreabaseball.com/Schedule/DailySchedule.aspx>
- 선발투수 보강 출처: KBO 공식 GameCenter 경기 목록
- 올레TV 채널번호 출처: <https://tv.kt.com/>
- 포함: 정규시즌, WC, 준PO, PO, KS
- 제외: 시범경기, 연습경기, 퓨처스, 올스타전, 국제대회, 기타 이벤트 경기
- 안내 범위: 합법 중계 정보만 안내하며 불법 스트리밍 또는 우회 링크는 수집하거나 발송하지 않습니다.

## 동작 방식

GitHub Actions는 혼잡한 정각 실행 지연에 대비해 Asia/Seoul 기준 08:17, 08:47, 09:17, 09:47에 오전 작업을 미리 시작합니다. 가장 먼저 실행된 작업이 10:00 KST까지 대기한 뒤 확인하며, 이후에는 10:17부터 23:47까지 30분마다 확인합니다. `concurrency`와 상태파일의 `first_sent`, 경기별 해시가 중복 발송을 막습니다.

이 공개 저장소에는 KIA 봇 코드와 상태만 보관합니다. 다른 봇의 workflow나 의존성과 실행 사용량을 공유하지 않으며, 정기 알림은 이 저장소의 GitHub Actions 한 경로에서만 발송합니다.

공개 저장소가 60일 동안 활동이 없으면 scheduled workflow가 비활성화될 수 있으므로 `.github/workflows/kia-workflow-guard.yml`이 매주 일요일 09:50 KST에 workflow를 다시 enable하고 heartbeat 커밋을 남깁니다.

10:00 KST에 오늘 KIA 경기가 있으면 최초 메시지를 1회 발송합니다. 오전 예약 작업이 비정상적으로 지연되거나 누락되면 `first_sent=false` 상태를 유지하고, 경기 시작 전 오후 첫 실행에서 최초 메시지를 보충 발송합니다. 취소·연기·지연 상태는 예정 시작시간이 지나도 누락하지 않고 상태 또는 사유가 바뀔 때 발송합니다. Daily Schedule에서 취소 경기가 빠지거나 사유가 일반 상태로만 표시되면 공식 Game List를 보완 데이터로 사용합니다. 이후 30분마다 경기시간, 선발투수, TV 중계, 취소 사유 등의 변동을 확인하며, 변동이 없으면 메시지를 보내지 않습니다.

오늘 KIA 경기가 없으면 기본적으로 발송하지 않습니다. GitHub Secret `SEND_NO_GAME`을 `true`로 설정하면 10:00 KST 이후 “오늘은 KIA 타이거즈 경기가 없습니다.”를 하루 1회만 보냅니다.

## 텔레그램 명령

봇에게 `/today`를 보내면 시간과 관계없이 현재 KBO GameCenter 경기 목록에 올라온 오늘 KIA 경기 정보와 선발투수를 같은 중계 알림 양식으로 답장합니다. 이 빠른 조회가 실패하거나 경기 목록이 비어 있으면 KBO Daily Schedule 경로로 재확인합니다. 예를 들어 선발투수가 등록된 경우 `KIA(네일) vs 키움(알칸타라)`처럼 표시합니다. 오늘 KIA 경기가 없으면 “오늘은 KIA 타이거즈 경기가 없습니다.”라고 답장합니다.

`/today`는 Vercel Telegram webhook이 즉시 처리합니다. `.github/workflows/kia-command.yml`은 문제 진단용 수동 실행만 지원하며, webhook과 충돌하는 정기 `getUpdates` 폴링은 실행하지 않습니다.

보안상 명령 응답은 기본적으로 `TELEGRAM_CHAT_ID`와 일치하는 채팅에서 온 메시지만 처리합니다.

## 즉시 응답 Webhook

`/today`를 거의 즉시 응답하게 하려면 이 저장소를 Vercel, Render, Railway 같은 HTTPS 배포 환경에 연결하고 Telegram webhook을 설정합니다. GitHub Actions 스케줄 알림은 그대로 유지되고, `/today` 명령만 webhook이 즉시 처리합니다.

Vercel 기준 webhook 엔드포인트는 아래 경로입니다.

```text
https://<배포도메인>/api/telegram
```

배포 환경 변수:

- `TELEGRAM_BOT_TOKEN`: BotFather 봇 토큰
- `TELEGRAM_CHAT_ID`: 허용할 채팅 ID
- `TELEGRAM_WEBHOOK_SECRET`: 임의의 긴 비밀 문자열

배포 URL이 나온 뒤 로컬에서 webhook을 설정합니다.

```powershell
$env:TELEGRAM_BOT_TOKEN="<BotFather 토큰>"
.\.venv\Scripts\python scripts\set_telegram_webhook.py --url "https://<배포도메인>/api/telegram" --secret "<TELEGRAM_WEBHOOK_SECRET>"
```

Telegram webhook이 활성화되면 `getUpdates` 폴링과 동시에 사용할 수 없습니다. 이 레포는 `/today`를 webhook 한 경로로만 처리하므로 정기 중계 알림 workflow와 충돌하지 않습니다.

## 더블헤더 처리

오늘 KIA 경기가 2경기 이상이면 경기시간 순으로 정렬하고 하나의 최초 메시지 안에 `DH 1차`, `DH 2차` 섹션을 나누어 발송합니다. 최초 발송 이후에는 변동이 생긴 경기 섹션만 재발송합니다. 예를 들어 `DH 1차`가 이미 시작했더라도 `DH 2차` 시작 전이면 `DH 2차`는 계속 30분마다 확인합니다.

공식 game id가 있으면 상태 키로 사용하고, 없으면 `날짜 + 상대팀 + 구장 + DH차수/단일경기`로 `game_key`를 만듭니다. 경기시간은 `game_key`에 넣지 않으므로 시간 변경만으로 새 경기로 오판하지 않습니다.

## 상태파일

상태는 `.bot_state/kia_YYYY-MM-DD.json`에 저장합니다.

- `first_sent`: 오늘 최초 경기 메시지 발송 여부
- `no_game_sent`: 경기 없음 메시지 발송 여부
- `games_by_key`: 경기별 마지막 발송 해시, 변동 발송 횟수, 마지막 스냅샷
- `last_sent_at_kst`: 마지막 발송 성공 시각

상태파일은 텔레그램 발송이 성공한 뒤에만 갱신합니다. 오래된 상태파일을 정리하는 함수도 포함되어 있습니다.

## 텔레그램 설정

1. Telegram에서 `@BotFather`를 열고 `/newbot`으로 봇을 생성합니다.
2. BotFather가 발급한 토큰을 복사합니다.
3. 봇을 받을 채팅방 또는 채널에 초대합니다.
4. `chat_id`를 확인합니다. 가장 단순한 방법은 봇에게 아무 메시지를 보낸 뒤 아래 주소를 브라우저에서 열어 `chat.id`를 확인하는 것입니다.

```text
https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/getUpdates
```

채널에 보낼 경우 봇을 채널 관리자로 추가하고 채널 username 또는 chat id를 `TELEGRAM_CHAT_ID`로 사용할 수 있습니다.

## GitHub Secrets

Repository Settings > Secrets and variables > Actions에서 아래 값을 등록합니다.

- `TELEGRAM_BOT_TOKEN`: BotFather에서 받은 봇 토큰
- `TELEGRAM_CHAT_ID`: 메시지를 받을 chat id 또는 채널 id
- `SEND_NO_GAME`: 선택값. `true`이면 경기 없음 메시지를 하루 1회 발송

## 실행

Actions 탭에서 `KIA Tigers Broadcast Bot` workflow를 선택한 뒤 `Run workflow`로 수동 실행할 수 있습니다. 스케줄 실행은 자동으로 동작하며, `concurrency` 설정으로 중복 실행을 막습니다.

workflow는 Python 3.11과 `requirements.txt`의 KIA 봇 전용 의존성만 사용합니다. 스케줄 실행에서는 KIA 테스트를 보조 검증으로 돌리고, 실행 후 `.bot_state`가 바뀌면 GitHub Actions bot 계정으로 commit/push합니다.

## 채널 표기

KBO 페이지의 TV 약어는 원문 대신 실제 채널명과 올레TV 채널번호로 표시합니다.

- `S-T`: SBS (5번)
- `K-2T`: KBS2 (7번)
- `K-1T`: KBS1 (9번)
- `M-T`: MBC (11번)
- `JTBC`: JTBC (15번)
- `SPO-T`: SPOTV (51번)
- `SPO-2T`: SPOTV2 (52번)
- `SS-T`: SBS SPORTS (58번)
- `KN-T`: KBS N SPORTS (59번)
- `MS-T`: MBC SPORTS+ (60번)
- `KBS LIFE`: KBS LIFE (158번)

위 목록에 없는 채널이 KBO에 나오면 KT 올레TV 공식 채널 편성표에서 채널명을 찾아 `채널명 (번호번)` 형식으로 표시합니다. 올레TV 편성표에서도 찾을 수 없는 채널만 KBO 표기 그대로 보냅니다. TV 값이 비어 있거나 파싱에 실패하면 `확인 필요`로 표시합니다. 선발투수가 아직 KBO GameCenter에 등록되지 않았으면 해당 투수명은 `확인 필요`로 표시합니다. 온라인 항목은 합법 중계 안내로 `TVING KBO`만 고정 표기합니다.

## 파서 유지보수

이 봇은 KBO 공식 Daily Schedule의 `DATE, TYPE, TIME, GAME, TV, LOCATION, ETC` 구조를 기준으로 파싱합니다. KBO 페이지의 HTML 표 구조나 표기 방식이 바뀌면 `parse_kbo_schedule()` 및 관련 테스트를 함께 수정해야 합니다.
