# Login and request checks

Every page needs the shared password except `/healthz`. Ten wrong passwords from one client lock that client out for 15 minutes without affecting others. A form posted from another site is refused.

## Sub-features

- `login-required` returns 401 without the password.
- `login-throttle` returns 429 on the eleventh wrong password from one client.
- `login-other-client` keeps another client working during that lockout.
- `cross-site-post` refuses a review post without the app's `Origin`.
- `security-headers` sends `X-Frame-Options`, the CSP, and `nosniff`.

## How to get to it (user POV)

- Open any page; the browser asks for a user name and the password.

## Driving it with verify.py

Preconditions:

- `$V doctor` reports `doctor: OK`.

- **Password required.** Run `$V raw GET / --password wrong --slug login-wrong`. Status 401.
- **Throttle.** Run `$V raw GET / --password wrong --header "cf-connecting-ip:198.51.100.7" --slug throttle` eleven times. The first ten return 401 and the eleventh returns 429.
- **Other client.** Right after, run `$V get / --slug other-client`. Status 200: this request has no `CF-Connecting-IP`, so the app counts it as `127.0.0.1`.
- **Cross-site post.** Run `$V raw POST /proposals/1/review --form decision=approved --form token=x --no-origin --slug cross-site`. Status 403.
- **Headers.** Run `$V raw GET /healthz --slug headers`. The saved `.txt` lists `x-frame-options: DENY`, `content-security-policy: frame-ancestors 'none'`, and `x-content-type-options: nosniff`. Every saved `.txt` lists them, 401 and 429 responses included.

## Gotchas

- The lockout lives in the app process. `$V down` and `$V up` clear it.
- On Render the client key is `CF-Connecting-IP`, set by Cloudflare. Locally a request without it counts as `127.0.0.1`, so all helper requests without the header share one counter.
