// Thin adapter to the pinned upstream utility. No timing inference or rewritten tokens.
const fs = require('node:fs');
const {createTikTokStyleCaptions} = require('@remotion/captions');
const groups = JSON.parse(fs.readFileSync(0, 'utf8'));
const result = groups.map(words => createTikTokStyleCaptions({
  captions: words.map(w => ({text: ' ' + w.text, startMs: Math.round(w.start * 1000),
    endMs: Math.round(w.end * 1000), timestampMs: null, confidence: null})),
  combineTokensWithinMilliseconds: 120000,
  breakOnSilenceAfterMilliseconds: 600,
}).pages.map(page => page.tokens.length));
process.stdout.write(JSON.stringify(result));
