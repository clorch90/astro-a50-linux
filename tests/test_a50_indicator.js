import {
    batteryColor,
    batteryIcon,
    microphoneIcon,
    parseMicrophoneStatus,
    parseStatus,
    SidetoneController,
    sidetoneLevel,
    sidetonePercent,
    toggledMicrophoneMute,
} from '../gnome-extension/a50-battery@astro-a50-linux/status.js';

function assert(condition, message) {
    if (!condition)
        throw new Error(message);
}

const charging = parseStatus('{"level":95,"charging":true,"reported_values":[100,95],"experimental":true}');
assert(charging.level === 95 && charging.charging, 'charging status');
assert(batteryIcon(95, true) === 'battery-level-90-charging-symbolic', 'charging icon');
assert(batteryIcon(29, false) === 'battery-level-20-symbolic', 'discharging icon');
assert(batteryColor(95, true) === '#33d17a', 'charging color');
assert(batteryColor(100, true) === '#26a269', 'fully charged color');
assert(batteryColor(20, false) === '#e01b24', 'critical battery color');
assert(batteryColor(21, false) === '#e5a50a', 'low battery color');
assert(batteryColor(40, false) === '#e5a50a', 'low battery upper boundary');
assert(batteryColor(41, false) === null, 'default theme color above low threshold');

for (const [level, percent] of [0, 17, 33, 50, 67, 83, 100].entries()) {
    assert(sidetoneLevel(level / 6) === level, `sidetone level ${level}`);
    assert(sidetonePercent(level) === percent, `sidetone percent ${level}`);
}
assert(sidetoneLevel(0.08) === 0, 'sidetone rounds down to zero');
assert(sidetoneLevel(0.09) === 1, 'sidetone rounds up to first level');
assert(sidetoneLevel(0.92) === 6, 'sidetone rounds up to maximum');

{
    const calls = [];
    const results = [];
    const errors = [];
    const timers = new Map();
    let timerId = 0;
    let resolveApply;
    const controller = new SidetoneController({
        apply: level => {
            calls.push(level);
            return new Promise(resolve => { resolveApply = resolve; });
        },
        showSelection: () => {},
        showResult: level => results.push(level),
        showError: error => errors.push(error),
        schedule: callback => {
            const id = ++timerId;
            timers.set(id, callback);
            return id;
        },
        cancel: id => timers.delete(id),
    });
    controller.beginDrag();
    controller.change(1);
    controller.change(2);
    assert(calls.length === 0, 'drag does not send before release');
    controller.endDrag();
    assert(calls.join(',') === '2', 'release sends final value');
    controller.beginDrag();
    controller.change(3);
    controller.change(4);
    controller.endDrag();
    assert(calls.join(',') === '2', 'pending value waits for in-flight command');
    resolveApply();
    await Promise.resolve();
    assert(calls.join(',') === '2,4', 'latest pending value is sent');
    assert(results.length === 0, 'stale result is not displayed');
    resolveApply();
    await Promise.resolve();
    assert(results.join(',') === '4', 'latest result is displayed');

    controller.change(1);
    controller.change(6);
    assert(timers.size === 1 && calls.length === 2, 'keyboard/scroll changes are coalesced');
    const callback = [...timers.values()][0];
    timers.clear();
    callback();
    assert(calls.join(',') === '2,4,6', 'keyboard/scroll sends latest value');
    resolveApply();
    await Promise.resolve();
    controller.change(3);
    controller.beginDrag();
    controller.endDrag();
    assert(calls.join(',') === '2,4,6,3', 'pending keyboard change is not lost on drag');
    resolveApply();
    await Promise.resolve();
    controller.change(5);
    controller.dispose();
    assert(timers.size === 0 && calls.length === 4, 'dispose cancels pending timer');
    assert(errors.length === 0, 'no unexpected sidetone errors');
}
{
    const errors = [];
    const controller = new SidetoneController({
        apply: async () => { throw new Error('device unavailable'); },
        showSelection: () => {},
        showResult: () => { throw new Error('failure reported as success'); },
        showError: error => errors.push(error.message),
        schedule: () => { throw new Error('unexpected timer'); },
        cancel: () => {},
    });
    controller.beginDrag();
    controller.change(1);
    controller.endDrag();
    await Promise.resolve();
    assert(errors.join(',') === 'device unavailable', 'sidetone errors are surfaced');
    controller.dispose();
}

const voice = 'alsa_input.usb-Logitech_A50-00.pro-input-0';
const game = 'alsa_input.usb-Logitech_A50-00.pro-input-1';
const microphoneNodes = (voiceMuted, gameMuted) => JSON.stringify([
    {id: 12, info: {props: {'node.name': voice, 'media.class': 'Audio/Source'}, params: {Props: [{mute: voiceMuted}]}}},
    {id: 13, info: {props: {'node.name': game, 'media.class': 'Audio/Source'}, params: {Props: [{mute: gameMuted}]}}},
    {id: 14, info: {props: {'node.name': 'unrelated', 'media.class': 'Audio/Source'}, params: {Props: [{mute: false}]}}},
]);

const muted = parseMicrophoneStatus(microphoneNodes(true, true));
assert(muted.state === 'muted', 'both microphones muted');
assert(muted.sources[voice].id === 12 && muted.sources[game].id === 13, 'microphone IDs');
assert(microphoneIcon(muted.state) === 'microphone-disabled-symbolic', 'muted icon');
assert(toggledMicrophoneMute(muted.state) === false, 'unmute when both are muted');

const active = parseMicrophoneStatus(microphoneNodes(false, false));
assert(active.state === 'unmuted', 'both microphones unmuted');
assert(microphoneIcon(active.state) === 'microphone-sensitivity-high-symbolic', 'active icon');
assert(toggledMicrophoneMute(active.state) === true, 'mute when both are active');

const mixed = parseMicrophoneStatus(microphoneNodes(true, false));
assert(mixed.state === 'mixed', 'mixed microphone states');
assert(microphoneIcon(mixed.state) === 'audio-input-microphone-symbolic', 'mixed icon');
assert(toggledMicrophoneMute(mixed.state) === true, 'mute both when mixed');

for (const value of [
    '{}',
    '{"level":101,"charging":false,"reported_values":[100,100],"experimental":true}',
    '{"level":95,"charging":"yes","reported_values":[100,95],"experimental":true}',
    '{"level":95,"charging":true,"reported_values":[100],"experimental":true}',
]) {
    let failed = false;
    try {
        parseStatus(value);
    } catch (error) {
        failed = true;
    }
    assert(failed, `invalid status accepted: ${value}`);
}
print('A50 indicator status tests passed');

for (const output of [
    '[]',
    JSON.stringify([{id: 12, info: {props: {'node.name': voice, 'media.class': 'Audio/Source'}, params: {Props: [{mute: true}]}}}]),
    JSON.stringify([
        {id: 12, info: {props: {'node.name': voice, 'media.class': 'Audio/Source'}, params: {Props: [{mute: 'yes'}]}}},
        {id: 13, info: {props: {'node.name': game, 'media.class': 'Audio/Source'}, params: {Props: [{mute: false}]}}},
    ]),
]) {
    let failed = false;
    try {
        parseMicrophoneStatus(output);
    } catch (error) {
        failed = true;
    }
    assert(failed, `invalid microphone status accepted: ${output}`);
}
