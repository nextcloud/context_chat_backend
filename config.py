config = {
	"embedder": {
		"n_ctx": 2048,  # context size of the model
		# "n_batch": 8,  # no. of tokens to process in parallel (1 <= n_batch <= n_ctx)
		# "n_threads": None,  # no. of threads to use, None for auto (n/2 if n > 1)
		# "n_gpu_layers": 0,  # no. of layers to be offloaded into gpu memory, -1 for all
		# "seed": -1,  # seed, -1 for random
	},
	"llm": {
		"n_ctx": 2048,  # context size of the model
		# "n_batch": 8,  # no. of tokens to process in parallel (1 <= n_batch <= n_ctx)
		# "n_threads": None,  # no. of threads to use, None for auto (n/2 if n > 1)
		# "n_gpu_layers": 0,  # no. of layers to be offloaded into gpu memory, -1 for all
		# "seed": -1,  # seed, -1 for random
	}
}

