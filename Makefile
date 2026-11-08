# Các lệnh hay dùng của vsub. Gõ `make` để xem danh sách.
#
# Ví dụ:
#   make gui
#   make sub IN="phim.mp4"
#   make vi IN="https://youtu.be/VIDEO_ID"
#   make clone IN="~/Downloads/phim.mp4"
#   make dub IN="phim.mp4" VOICE="Thiện Minh"

SHELL := /bin/bash
.DEFAULT_GOAL := help

UV    ?= uv
VSUB  := $(UV) run vsub
IN    ?=
ARGS  ?=
VOICE ?= Trúc Ly
LANG_SRC ?=

# --lang chỉ thêm khi có LANG_SRC (bỏ trống = tự nhận ngôn ngữ)
lang_flag = $(if $(LANG_SRC),--lang $(LANG_SRC))

# IN đi qua biến môi trường để giữ nguyên khoảng trắng; "~/..." được đổi thành $HOME/...
export IN
in := "$${IN/\#\~/$$HOME}"

define need_in
	@if [ -z "$$IN" ]; then echo 'Thiếu IN: file video hoặc link YouTube, ví dụ  make $@ IN="phim.mp4"'; exit 1; fi
endef

.PHONY: help setup sync dev gui sub vi dub-new clone dub dub-clone doctor install-vieneu \
        test build-mac build-win update-ytdlp clean

help: ## Hiện danh sách lệnh
	@echo "Dùng: make <lệnh> [IN=...] [ARGS=...]"
	@echo
	@grep -E '^[a-zA-Z_-]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'
	@echo
	@echo "Biến: IN (video / link YouTube), LANG_SRC (ngôn ngữ gốc: ja, en, zh…), VOICE (giọng), ARGS (tuỳ chọn thêm)"

# ---------------------------------------------------------------- cài đặt

setup: ## Cài lần đầu trên Mac: ffmpeg, uv, thư viện Python, tạo Vsub.app
	bash setup.command

sync: ## Cài / cập nhật thư viện Python theo uv.lock
	$(UV) sync

dev: ## Cài thêm công cụ phát triển (pytest)
	$(UV) sync --extra dev

doctor: ## Kiểm tra FFmpeg, Whisper, Claude, VieNeu
	$(VSUB) doctor

install-vieneu: ## Cài VieNeu-TTS để thuyết minh
	$(VSUB) doctor --install vieneu

update-ytdlp: ## Cập nhật yt-dlp khi YouTube đổi cách chặn
	$(UV) lock --upgrade-package yt-dlp
	$(UV) sync

# ---------------------------------------------------------------- dùng app

gui: ## Mở giao diện
	$(UV) run vsub-gui

sub: ## Tạo phụ đề gốc (.srt)  IN=video|link
	$(need_in)
	$(VSUB) $(in) $(lang_flag) $(ARGS)

vi: ## Tạo phụ đề + dịch sang tiếng Việt  IN=video|link
	$(need_in)
	$(VSUB) $(in) $(lang_flag) --to vi $(ARGS)

dub-new: ## Phụ đề + dịch + thuyết minh giọng có sẵn  IN=video|link [VOICE=...]
	$(need_in)
	$(VSUB) $(in) $(lang_flag) --to vi --dub --voice "$(VOICE)" $(ARGS)

clone: ## Phụ đề + dịch + thuyết minh giọng clone  IN=video|link
	$(need_in)
	$(VSUB) $(in) $(lang_flag) --to vi --dub --voice clone $(ARGS)

dub: ## Chỉ thuyết minh từ <tên>.vi.srt có sẵn  IN=video [VOICE=...]
	$(need_in)
	$(VSUB) dub $(in) --voice "$(VOICE)" $(ARGS)

dub-clone: ## Chỉ thuyết minh từ .vi.srt bằng giọng clone  IN=video
	$(need_in)
	$(VSUB) dub $(in) --voice clone $(ARGS)

# ---------------------------------------------------------------- phát triển

test: ## Chạy test
	$(UV) run --extra dev pytest -q

build-mac: ## Đóng gói dist/vsub-mac-universal.zip
	bash scripts/build_mac.sh

build-win: ## Đóng gói bản Windows (cần PowerShell 7: pwsh)
	pwsh scripts/build_windows.ps1

clean: ## Xoá dist/, __pycache__, egg-info
	rm -rf dist src/*.egg-info
	find . -name __pycache__ -type d -not -path './.venv/*' -prune -exec rm -rf {} +
