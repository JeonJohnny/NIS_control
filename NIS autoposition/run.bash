#!/usr/bin/env bash
# ND Generator UI 실행 스크립트 (Anaconda base 환경)
#
# 사용법 (Git Bash / MSYS2 / WSL):
#   ./run.bash            # nd_generator_ui.py 실행
#   ./run.bash --help     # 추가 인자는 그대로 파이썬 스크립트에 전달됨
#
# 다른 conda 설치 경로를 쓰는 경우:
#   CONDA_ROOT=/c/ProgramData/Anaconda3 ./run.bash

set -euo pipefail

# 스크립트가 놓인 디렉터리를 작업 디렉터리로 (더블클릭/타 경로 실행 대비)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

ENV_NAME="${CONDA_ENV:-base}"
TARGET="nd_generator_ui.py"

if [[ ! -f "$TARGET" ]]; then
    echo "[ERROR] 실행 대상 파일이 없습니다: $SCRIPT_DIR/$TARGET" >&2
    exit 1
fi

# ---------------------------------------------------------------------------
# 1순위: 폴더에 동봉된 런타임 (설치 불필요, 폴더째 옮겨도 동작)
# ---------------------------------------------------------------------------
if [[ -x "python/python.exe" && "${ND_USE_SYSTEM_PYTHON:-}" != "1" ]]; then
    echo "[INFO] runtime : 동봉 런타임 (python/)"
    echo "[INFO] run     : $TARGET"
    echo
    exec "./python/python.exe" "$TARGET" "$@"
fi

# ---------------------------------------------------------------------------
# 2순위: 시스템 conda — conda 설치 위치 찾기
# ---------------------------------------------------------------------------
find_conda_root() {
    # 1) 사용자가 직접 지정
    if [[ -n "${CONDA_ROOT:-}" ]]; then
        echo "$CONDA_ROOT"
        return
    fi
    # 2) 이미 활성화된 conda 세션
    if [[ -n "${CONDA_EXE:-}" ]]; then
        dirname "$(dirname "$CONDA_EXE")"
        return
    fi
    # 3) PATH 상의 conda
    if command -v conda >/dev/null 2>&1; then
        dirname "$(dirname "$(command -v conda)")"
        return
    fi
    # 4) 흔한 설치 경로 탐색
    local candidate
    for candidate in \
        "$HOME/anaconda3" \
        "$HOME/Anaconda3" \
        "$HOME/miniconda3" \
        "$HOME/miniforge3" \
        "/c/ProgramData/Anaconda3" \
        "/c/ProgramData/miniconda3" \
        "/opt/anaconda3" \
        "/opt/miniconda3"
    do
        if [[ -d "$candidate" ]]; then
            echo "$candidate"
            return
        fi
    done
}

CONDA_ROOT="$(find_conda_root || true)"

if [[ -z "$CONDA_ROOT" || ! -d "$CONDA_ROOT" ]]; then
    echo "[ERROR] 동봉 런타임(python/python.exe)도, Anaconda 도 찾지 못했습니다." >&2
    echo "        CONDA_ROOT 환경변수로 직접 지정하세요. 예:" >&2
    echo "        CONDA_ROOT=/c/Users/\$USER/anaconda3 ./run.bash" >&2
    exit 1
fi

# ---------------------------------------------------------------------------
# base 환경 활성화
# ---------------------------------------------------------------------------
if [[ -f "$CONDA_ROOT/etc/profile.d/conda.sh" ]]; then
    # shellcheck disable=SC1091
    source "$CONDA_ROOT/etc/profile.d/conda.sh"
    conda activate "$ENV_NAME"
    PYTHON=python
else
    # conda.sh가 없으면 환경의 인터프리터를 직접 사용 (Windows/Unix 레이아웃 모두 대응)
    if [[ "$ENV_NAME" == "base" ]]; then
        ENV_PREFIX="$CONDA_ROOT"
    else
        ENV_PREFIX="$CONDA_ROOT/envs/$ENV_NAME"
    fi

    if [[ -x "$ENV_PREFIX/python.exe" ]]; then
        PYTHON="$ENV_PREFIX/python.exe"
        # Windows용 DLL/스크립트 경로를 PATH에 추가 (numpy 등 로딩에 필요)
        export PATH="$ENV_PREFIX:$ENV_PREFIX/Library/bin:$ENV_PREFIX/Library/usr/bin:$ENV_PREFIX/Library/mingw-w64/bin:$ENV_PREFIX/Scripts:$PATH"
    elif [[ -x "$ENV_PREFIX/bin/python" ]]; then
        PYTHON="$ENV_PREFIX/bin/python"
        export PATH="$ENV_PREFIX/bin:$PATH"
    else
        echo "[ERROR] '$ENV_NAME' 환경의 python을 찾지 못했습니다: $ENV_PREFIX" >&2
        exit 1
    fi
fi

echo "[INFO] conda root : $CONDA_ROOT"
echo "[INFO] env        : $ENV_NAME"
echo "[INFO] python     : $("$PYTHON" -c 'import sys; print(sys.executable)')"
echo "[INFO] run        : $TARGET"
echo

exec "$PYTHON" "$TARGET" "$@"
