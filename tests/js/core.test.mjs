import { test } from "node:test";
import assert from "node:assert/strict";
import {
  parseLrc, activeIndex, songPosition, driftAction, teleprompterRate, teleprompterOffset, sliderToGain,
} from "../../karaoke/static/core.js";

test("parseLrc handles metadata, repeats and hebrew", () => {
  const lines = parseLrc("[ar:x]\n[00:30.00][00:10.00]פזמון, כן!\n[00:20.5]verse\n");
  assert.deepEqual(lines.map((l) => [l.t, l.text]), [[10, "פזמון, כן!"], [20.5, "verse"], [30, "פזמון, כן!"]]);
});

test("activeIndex", () => {
  const lines = [{ t: 1 }, { t: 5 }, { t: 9 }];
  assert.equal(activeIndex(lines, 0.5), -1);
  assert.equal(activeIndex(lines, 1), 0);
  assert.equal(activeIndex(lines, 8.99), 1);
  assert.equal(activeIndex(lines, 100), 2);
  assert.equal(activeIndex([], 3), -1);
});

test("songPosition subtracts output latency and clamps", () => {
  assert.equal(songPosition(110, 100, 5, 0.2), 14.8);
  assert.equal(songPosition(100, 100, 0, 0.3), 0);
});

test("driftAction nudges small drift and seeks large drift with hysteresis", () => {
  assert.deepEqual(driftAction(0.02, 10), { rate: 1 });
  assert.deepEqual(driftAction(0.2, 10), { rate: 0.95 });   // video ahead -> slow down
  assert.deepEqual(driftAction(-0.2, 10), { rate: 1.05 });  // video behind -> speed up
  assert.deepEqual(driftAction(0.8, 10, 5), { seek: true });
  assert.deepEqual(driftAction(0.8, 10, 9.5), { rate: 1 }); // seeked <1s ago: wait
});

test("teleprompter scrolls between vocal onsets", () => {
  const rate = teleprompterRate(1000, 10, 110, 200);
  assert.equal(rate, 10);
  assert.equal(teleprompterOffset(0, 1, rate, 1, 5, 10), 0);
  assert.equal(teleprompterOffset(100, 0.5, rate, 2, 20, 10), 110);
  assert.equal(teleprompterRate(500, null, null, 100), 5);
});

test("sliderToGain", () => {
  assert.equal(sliderToGain(0), 0);
  assert.equal(sliderToGain(100), 1);
  assert.equal(sliderToGain(50), 0.25);
  assert.equal(sliderToGain(150), 1);
});
