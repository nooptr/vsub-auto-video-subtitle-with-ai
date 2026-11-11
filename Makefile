# Các lệnh hay dùng của vsub. Gõ `make` để xem danh sách.
#
# Ví dụ:
#   make gui
#   make sub phim.mp4
#   make vi "https://www.youtube.com/watch?v=VIDEO_ID"
#   make vi https://x.com/USER/status/TWEET_ID
#   make clone ~/Downloads/phim.mp4
#   make dub phim.mp4 VOICE="Thiện Minh"
#   make vi phim.mp4 OUT=~/PhuDe   # lưu kết quả vào ~/PhuDe thay vì cạnh video
#   make vi IN="phim.mp4"          # cách cũ vẫn dùng được

SHELL := /bin/bash
.DEFAULT_GOAL := help

UV    ?= uv
VSUB  := $(UV) run vsub
IN    ?=
ARGS  ?=
VOICE ?= Trúc Ly
LANG_SRC ?=
COOKIES ?=
OUT ?=

# --cookies-from-browser chỉ thêm khi có COOKIES (trình duyệt lấy cookie YouTube / X khi bị chặn)
cookie_flag = $(if $(COOKIES),--cookies-from-browser $(COOKIES))

# --out-dir chỉ thêm khi có OUT (thư mục lưu kết quả; bỏ trống = cạnh video)
out_flag = $(if $(OUT),--out-dir "$(OUT)")

# --lang chỉ thêm khi có LANG_SRC (bỏ trống = tự nhận ngôn ngữ)
lang_flag = $(if $(LANG_SRC),--lang $(LANG_SRC))

# Cho phép ghi thẳng video / link sau tên lệnh:  make clone https://youtu.be/VIDEO_ID
# Các từ sau tên lệnh được ghép lại thành IN, và không bị make hiểu là lệnh khác.
RUN_GOALS := sub vi dub-new clone dub dub-clone
ifneq ($(filter $(firstword $(MAKECMDGOALS)),$(RUN_GOALS)),)
  POS := $(wordlist 2,$(words $(MAKECMDGOALS)),$(MAKECMDGOALS))
  ifneq ($(POS),)
    IN := $(POS)
  endif
  %::
	@:
endif

# IN đi qua biến môi trường để giữ nguyên khoảng trắng; "~/..." được đổi thành $HOME/...
export IN
in := "$${IN/\#\~/$$HOME}"

define need_in
	@if [ -z "$$IN" ]; then echo 'Thiếu video: ghi file video hoặc link YouTube / X sau tên lệnh, ví dụ  make $@ phim.mp4'; exit 1; fi
endef

.PHONY: help setup sync dev gui sub vi dub-new clone dub dub-clone doctor install-vieneu \
        test build-mac build-win update-ytdlp clean

help: ## Hiện danh sách lệnh
	@echo "Dùng: make <lệnh> [video | link YouTube / X] [OUT=...] [VOICE=...] [LANG_SRC=...] [ARGS=...]"
	@echo
	@grep -E '^[a-zA-Z_-]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'
	@echo
	@echo "Biến: IN (thay cho ghi video sau tên lệnh), LANG_SRC (ngôn ngữ gốc: ja, en, zh…), VOICE (giọng), COOKIES (chrome, firefox… khi YouTube / X chặn), OUT (thư mục lưu kết quả), ARGS (tuỳ chọn thêm)"

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

update-ytdlp: ## Cập nhật yt-dlp khi YouTube / X đổi cách chặn
	$(UV) lock --upgrade-package yt-dlp
	$(UV) sync

# ---------------------------------------------------------------- dùng app

gui: ## Mở giao diện
	$(UV) run vsub-gui

sub: ## Tạo phụ đề gốc (.srt)  <video|link>
	$(need_in)
	$(VSUB) $(in) $(lang_flag) $(cookie_flag) $(out_flag) $(ARGS)

vi: ## Tạo phụ đề + dịch sang tiếng Việt  <video|link>
	$(need_in)
	$(VSUB) $(in) $(lang_flag) $(cookie_flag) --to vi $(out_flag) $(ARGS)

dub-new: ## Phụ đề + dịch + thuyết minh giọng có sẵn  <video|link> [VOICE=...]
	$(need_in)
	$(VSUB) $(in) $(lang_flag) $(cookie_flag) --to vi --dub --voice "$(VOICE)" $(out_flag) $(ARGS)

clone: ## Phụ đề + dịch + thuyết minh giọng clone  <video|link>
	$(need_in)
	$(VSUB) $(in) $(lang_flag) $(cookie_flag) --to vi --dub --voice clone $(out_flag) $(ARGS)

dub: ## Chỉ thuyết minh từ <tên>.vi.srt có sẵn  <video> [VOICE=...]
	$(need_in)
	$(VSUB) dub $(in) --voice "$(VOICE)" $(out_flag) $(ARGS)

dub-clone: ## Chỉ thuyết minh từ .vi.srt bằng giọng clone  <video>
	$(need_in)
	$(VSUB) dub $(in) --voice clone $(out_flag) $(ARGS)

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
