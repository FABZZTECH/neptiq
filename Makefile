# NEPTIQ — Makefile
#
# Task 0 provides only the `brand` target. Task 1 will add dev, test, lint,
# migrate, fixtures per docs/ARCHITECTURE.md. Do not add targets ahead of
# the task that implements what they front.

.PHONY: brand

brand:
	@bash scripts/build-brand.sh
