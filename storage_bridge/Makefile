VERILATOR ?= verilator
RTL := $(addprefix rtl/,$(shell cat rtl/files.f))
WIDTH ?= 256
PLANES ?= 1

.PHONY: lint
lint:
	$(VERILATOR) --lint-only --top-module storage_bridge_top -Wall --unroll-count 512 \
		-Wno-WIDTHEXPAND -Wno-WIDTHTRUNC -Wno-UNUSEDSIGNAL -Wno-UNUSEDPARAM \
		-Wno-PINCONNECTEMPTY \
		-GAXI_DATA_WIDTH=$(WIDTH) -GRESOURCE_PLANES=$(PLANES) $(RTL)
