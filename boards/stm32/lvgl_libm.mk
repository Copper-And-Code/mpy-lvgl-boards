# Single-precision libm functions that LVGL 9.5 calls (sinf, cosf, atan2f, sqrtf;
# math.c for scalbnf), for boards built with MICROPY_FLOAT_IMPL = double: the port
# then links only lib/libm_dbl, which has the double versions.
# Included by the boards' mpconfigboard.mk.
ifeq ($(MICROPY_FLOAT_IMPL),double)
LIBM_SRC_C += $(addprefix lib/libm/,\
	sf_sin.c \
	sf_cos.c \
	kf_sin.c \
	kf_cos.c \
	ef_rem_pio2.c \
	kf_rem_pio2.c \
	atan2f.c \
	atanf.c \
	thumb_vfp_sqrtf.c \
	math.c \
	)
endif
