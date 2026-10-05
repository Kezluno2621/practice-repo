# Practice Repository

OSS 기반 SW 프로그래밍 수업의 Git/GitHub 개발 환경 실습을 위한 저장소입니다.

## Purpose

- Git 기본 설정 확인
- GitHub SSH 연결
- Commit 및 Push 실습
- DORA metric 수집 자동화
> DORA 4대 지표
    - Lead Time
    - Deployment Frequency
    - MTTR
    - Change Failure Rate
----
## DORA Metrics Automation

[리포트 화면](/image/dora_metric_report.png)
[실행 성공 로그 스크린샷](/image/dora_metric_sc_log.png)
### Overview

`DORA Metrics Automation`은 GitHub Actions와 GitHub REST API를 사용해 최근 7일의 실제 deployment 데이터를 기준으로 DORA 4대 지표를 자동 수집합니다. 데이터가 부족한 지표는 0으로 추정하지 않고 `N/A`(`null`)로 표시합니다.

### Metrics

- **Lead Time for Changes**: 성공한 deployment가 가리키는 commit 시각부터 deployment 성공 상태가 생성된 시각까지의 평균 시간(hours)
- **Deployment Frequency**: 측정 기간에 성공한 deployment 수를 주 단위로 환산한 값(deployments/week). JSON에는 실제 성공 건수인 `deployment_count`도 함께 기록됩니다.
- **Mean Time To Restore (MTTR)**: 실패 또는 오류 deployment부터 그 이후 첫 성공 deployment까지 걸린 시간의 평균(hours). 실패가 없거나 아직 복구되지 않았다면 `N/A`입니다.
- **Change Failure Rate**: `실패·오류 deployment / (성공 + 실패·오류 deployment) × 100`. 완료된 deployment가 없으면 `N/A`입니다.

측정 기간은 기본 7일이며 수동 실행 시 `period_days` 입력으로 변경할 수 있습니다. GitHub의 각 deployment에서 최신 terminal status(`success`, `failure`, `error`)를 사용합니다.

### Workflow

```text
Pull Request / Deployment
          ↓
GitHub Actions → GitHub REST API → DORA 계산
          ↓                         ↓
     JSON Artifact          Chart.js Dashboard
          ↓
Weekly GitHub Issue (schedule 또는 수동 선택 시)
```

워크플로는 merge/close된 Pull Request, deployment status 변경, 수동 실행, 매주 월요일 00:00 UTC(한국 시간 09:00)에 실행됩니다. 주간 schedule 실행은 `dora-report` 라벨을 준비한 뒤 보고서 내용을 GitHub Issue로 생성합니다. 수동 실행은 `create_weekly_report`를 선택한 경우에만 Issue를 만듭니다.

### Files

- `.github/workflows/metrics.yml`: 트리거, 최소 권한, 수집·Artifact·Issue 단계를 정의합니다.
- `scripts/collect_dora.py`: API 페이지네이션, DORA 계산, JSON/Markdown/HTML 생성을 담당합니다.
- `dashboard/index.html`: 실제 JSON이 삽입되는 반응형 Chart.js 대시보드 템플릿입니다.
- `reports/README.md`: 런타임 결과물과 Artifact를 설명합니다.

### How to Run

1. GitHub 저장소의 **Actions** 탭으로 이동합니다.
2. **DORA Metrics Automation**을 선택합니다.
3. **Run workflow**를 누릅니다.
4. 필요하면 기간과 주간 Issue 생성 여부를 지정하고 실행합니다.
5. 실행 완료 후 **Artifacts**에서 `dora-metrics`를 다운로드합니다.
6. 압축을 풀고 `dashboard.html`을 브라우저로 엽니다.

로컬 실행은 저장소 루트에서 `GITHUB_TOKEN`, `GITHUB_REPOSITORY=owner/practice-repo`, 선택적으로 `PERIOD_DAYS` 환경 변수를 설정한 뒤 `python scripts/collect_dora.py`를 실행합니다. Personal Access Token이나 API Key는 코드에 저장하지 않습니다.

### Result

각 실행의 `dora-metrics` Artifact에는 다음 파일이 포함됩니다.

- `dora-metrics.json`: 기계 판독용 지표와 생성 시각
- `dashboard.html`: 4개 카드와 Chart.js 그래프
- `weekly-report.md`: 측정 기간, 표, 데이터 상태 요약

### 생성형 AI를 사용해 작성하였음을 밝힙니다.