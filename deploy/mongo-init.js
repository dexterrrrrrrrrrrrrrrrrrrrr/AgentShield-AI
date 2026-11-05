// Runs only when this NEW MongoDB 7 volume is initialized. Never log passwords.
const name = process.env.MONGO_INITDB_DATABASE;
const username = process.env.MONGO_APP_USER;
const password = process.env.MONGO_APP_PASSWORD;
if (!name || !/^[A-Za-z0-9_]+$/.test(name) || !username || !/^[A-Za-z0-9_-]+$/.test(username) || !password || !/^[A-Za-z0-9_-]{32,}$/.test(password)) {
  throw new Error("Use a database identifier and URL-safe app credentials; app password needs at least 32 characters");
}
db.getSiblingDB(name).createUser({
  user: username,
  pwd: password,
  roles: [{ role: "readWrite", db: name }],
});
