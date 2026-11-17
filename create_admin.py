import getpass,secrets,sqlite3,sys
from app import connect,pw_hash
email=input('Admin email: ').strip().lower()
password=getpass.getpass('Admin password (min 12 characters): ')
if '@' not in email or len(password)<12:sys.exit('Invalid email or password shorter than 12 characters')
salt=secrets.token_hex(16)
with connect() as c:
 c.execute('INSERT INTO users(email,salt,password_hash,active,admin) VALUES(?,?,?,?,1)',(email,salt,pw_hash(password,salt),1))
print('Admin created. Do not share credentials.')
