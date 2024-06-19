import os

'''
To introduce version based repairs instead of maintaining a list of executed repairs
'''

persistent_storage_path = os.getenv('APP_PERSISTENT_STORAGE', 'persistent_storage')
repair_info_path = os.path.join(persistent_storage_path, 'repair.info')
version_info_path = os.path.join(persistent_storage_path, 'version.info')

# remove the repair info file if it exists
if os.path.exists(repair_info_path):
	os.unlink(repair_info_path)

# create the version info file if it does not exist
# and write the version to it, raise if APP_VERSION is not set
if not os.path.exists(version_info_path):
	with open(version_info_path, 'w') as f:
		f.write(os.environ['APP_VERSION'])
