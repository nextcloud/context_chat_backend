def value_of(value: str | None, default: str | None = None) -> str | None:
	if value is None or value.strip() == '':
		return default
	return value


# class name/index name is capitalized (user1 => User1) maybe because it is
# a class name, so the solution is to use Vector_user1 instead of user1
def CLASS_NAME(user_id): return f"Vector_{user_id}"


VECTOR_DB = 0b1
EMBEDDING_MODEL = 0b10

