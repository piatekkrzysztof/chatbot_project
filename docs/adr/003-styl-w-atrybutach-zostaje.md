# 003 — `style-src 'unsafe-inline'` stays

**Status:** accepted, knowingly
**Date:** 4 September 2026

## Decision

The Content Security Policy closes scripts and leaves styles open:

```
script-src 'nonce-...' 'strict-dynamic'
style-src  'self' 'unsafe-inline'
```

## Why the two halves are not the same

`script-src 'unsafe-inline'` meant the browser would execute any script written
into the page, including one that arrived by injection. That was the hole worth
closing, and it is closed: scripts now need a nonce that is generated per
request, and an injected string cannot carry one because it does not exist yet
when the injection happens.

Styles cannot read a variable or send a request. The attacks they enable are
real but narrow — a CSS selector can leak the *presence* of an attribute value
by requesting a background image per candidate character, which needs
`img-src` to cooperate; here `img-src` allows `https:` broadly, so this is not
purely theoretical. What it cannot do is read the access token, which lives in
a JavaScript variable and is invisible to CSS.

## What it costs

A narrow exfiltration channel stays open for anything rendered into an
attribute value. Given the panel renders customer names, e-mail addresses and
document titles, an attacker with an injection point could extract those slowly
and noisily.

## What was rejected

**Nonces on styles.** React sets styles as element attributes — `style="..."`
— and so does Tailwind for arbitrary values. A nonce does not apply to
attributes at all, only to `<style>` elements, so this would not work without
rewriting how components apply styles.

**Hashes.** The set of inline styles changes with the data being rendered, so
the hashes would change per response.

**Removing inline styles entirely.** Possible, and the correct end state. It
means auditing every component for `style=` and every Tailwind arbitrary value,
in an application whose UI is still moving. The cost is high and the closed
script hole was where the token risk actually was.

## What should make somebody revisit this

- the panel starts rendering content supplied by a third party (today it
  renders the tenant's own data and the bot's own output),
- `img-src` is tightened, which would make the selector-based channel much
  harder and change the calculation,
- a UI freeze creates a window where auditing every inline style is cheap.
