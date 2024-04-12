#!/usr/bin/env sh

set -e

if [ -f hwdetected ]; then
	echo "Hardware detection already done. Remove \"hwdetected\" file to run again."
	exit 0
fi

# if argument is provided, use it as the accelerator
if [ "$1" = "cpu" ] || [ "$1" = "cuda" ]; then
	echo "Using provided hardware: $1"
	accel="$1"
elif [ -z "$2" ]; then
	echo "Detecting hardware..."

	lspci_out=$(lspci)
	if echo "$lspci_out" | grep -q "VGA.*NVIDIA"; then
		accel="cuda"
	else
		accel="cpu"
	fi

	echo "Detected hardware: $accel"
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

if [ "$accel" = "cuda" ]; then
	torch_variant="cu118"
	cmake_args="-DLLAMA_CUBLAS=on -DLLAMA_BLAS=on -DLLAMA_BLAS_VENDOR=OpenBLAS"
else
	torch_variant="cpu"
	cmake_args="-DLLAMA_BLAS=on -DLLAMA_BLAS_VENDOR=OpenBLAS"
fi

python3 -m pip install --no-cache-dir --force-reinstall "torch==2.2.2+$torch_variant" "torchvision==0.17.2+$torch_variant" -f https://download.pytorch.org/whl/torch_stable.html
if [ $? -ne 0 ]; then
	echo "Failed to install torch"
	exit 1
fi

CMAKE_ARGS="$cmake_args" python3 -m pip install --no-cache-dir --force-reinstall llama-cpp-python==0.2.57
if [ $? -ne 0 ]; then
	echo "Failed to install llama-cpp-python"
	exit 1
fi

touch hwdetected
