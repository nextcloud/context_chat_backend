def value_of(value: str | None, default: str | None = None) -> str | None:
  if value is None or value.strip() == '':
    return default
  return value


# class name/index name is capitalized (user1 => User1) maybe because it is a class name,
# so the solution is to use Vector_user1 instead of user1
CLASS_NAME = lambda user_id: f"Vector_{user_id}"

