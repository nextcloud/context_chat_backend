#!/usr/bin/env sh

set -e

accel=$COMPUTE_DEVICE
if [ "$accel" = "ROCM" ]; then
	accel="CUDA"
fi

# if the COMPUTE_DEVICE env var is not set, try to detect the hardware
if [ -z "$accel" ]; then
	echo "Detecting hardware..."

	lspci_out=$(lspci)
	if echo "$lspci_out" | grep -q -E "(VGA|3D).*NVIDIA"; then
		accel="CUDA"
	else
		accel="CPU"
	fi

	echo "Detected hardware: $accel"
fi

# llama.cpp fix for cpu in docker
if [ "${AA_DOCKER_ENV:-0}" = "1" ] && [ "$accel" = "CPU" ]; then
	ln -sf /usr/local/cuda/compat/libcuda.so.1 /lib/x86_64-linux-gnu/
fi

# if argument is "config", copy the detected hw config to the persistent storage and exit
if [ "$1" = "config" ]; then
	if [ ! -d "$APP_PERSISTENT_STORAGE" ]; then
		echo "Persistent storage location \"$APP_PERSISTENT_STORAGE\" does not exist"
		exit 1
	fi

	# if second argument is provided, use it as the accelerator
	if [ -n "$2" ] && ([ "$2" = "cpu" ] || [ "$2" = "cuda" ]); then
		echo "Using provided hardware: $2"
		accel="$2"
	fi

	if [ -f "$APP_PERSISTENT_STORAGE/config.yaml" ]; then
		echo "Config file already exists in the persistent storage (\"$APP_PERSISTENT_STORAGE/config.yaml\")."
		exit 0
	fi

	echo "Copying config file to the persistent storage..."
	if [ "$accel" = "cuda" ]; then
		cp "config.gpu.yaml" "$APP_PERSISTENT_STORAGE/config.yaml"
	else
		cp "config.cpu.yaml" "$APP_PERSISTENT_STORAGE/config.yaml"
	fi

	exit 0
fi
