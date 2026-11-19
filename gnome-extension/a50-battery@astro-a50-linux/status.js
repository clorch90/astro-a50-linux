export function parseStatus(output) {
    const status = JSON.parse(output);
    if (!status || !Number.isInteger(status.level) ||
        status.level < 0 || status.level > 100 ||
        typeof status.charging !== 'boolean' ||
        status.experimental !== true ||
        !Array.isArray(status.reported_values) ||
        status.reported_values.length !== 2 ||
        !status.reported_values.every(value =>
            Number.isInteger(value) && value >= 0 && value <= 100))
        throw new Error('Invalid A50 battery data');
    return status;
}

export function batteryIcon(level, charging) {
    const rounded = Math.floor(level / 10) * 10;
    const suffix = charging
        ? (rounded === 100 ? '-charged' : '-charging')
        : '';
    return `battery-level-${rounded}${suffix}-symbolic`;
}

export function batteryColor(level, charging) {
    if (charging)
        return level === 100 ? '#26a269' : '#33d17a';
    if (level <= 20)
        return '#e01b24';
    if (level <= 40)
        return '#e5a50a';
    return null;
}

export function sidetoneLevel(value) {
    if (!Number.isFinite(value) || value < 0 || value > 1)
        throw new Error('Invalid sidetone slider value');
    return Math.round(value * 6);
}

export function sidetonePercent(level) {
    if (!Number.isInteger(level) || level < 0 || level > 6)
        throw new Error('Invalid sidetone level');
    return Math.round(level * 100 / 6);
}

export class SidetoneController {
    constructor({apply, showSelection, showResult, showError, schedule, cancel}) {
        this._apply = apply;
        this._showSelection = showSelection;
        this._showResult = showResult;
        this._showError = showError;
        this._schedule = schedule;
        this._cancel = cancel;
        this._dragging = false;
        this._dirty = false;
        this._pending = null;
        this._timer = null;
        this._busy = false;
        this._disposed = false;
    }

    beginDrag() {
        this._dragging = true;
        this._dirty = this._timer !== null;
        this._clearTimer();
    }

    change(level) {
        this._level = level;
        this._showSelection(level);
        if (this._dragging) {
            this._dirty = true;
            return;
        }
        this._clearTimer();
        this._timer = this._schedule(() => {
            this._timer = null;
            this._queue(level);
        });
    }

    endDrag() {
        this._dragging = false;
        if (this._dirty) {
            this._dirty = false;
            this._queue(this._level);
        }
    }

    dispose() {
        this._disposed = true;
        this._clearTimer();
        this._pending = null;
    }

    _clearTimer() {
        if (this._timer !== null) {
            this._cancel(this._timer);
            this._timer = null;
        }
    }

    async _queue(level) {
        if (this._disposed)
            return;
        this._pending = level;
        if (this._busy)
            return;
        this._busy = true;
        while (!this._disposed && this._pending !== null) {
            const next = this._pending;
            this._pending = null;
            try {
                await this._apply(next);
                if (!this._disposed && this._pending === null &&
                    !this._dragging && this._timer === null)
                    this._showResult(next);
            } catch (error) {
                if (!this._disposed)
                    this._showError(error);
            }
        }
        this._busy = false;
    }
}

const A50_SOURCES = new Set([
    'alsa_input.usb-Logitech_A50-00.pro-input-0',
    'alsa_input.usb-Logitech_A50-00.pro-input-1',
]);

export function parseMicrophoneStatus(output) {
    const nodes = JSON.parse(output);
    const sources = {};
    for (const node of nodes) {
        const info = node.info ?? {};
        const props = info.props ?? {};
        const name = props['node.name'];
        if (!A50_SOURCES.has(name) || props['media.class'] !== 'Audio/Source')
            continue;
        const mute = info.params?.Props?.find(
            item => item && typeof item === 'object' &&
                typeof item.mute === 'boolean')?.mute;
        if (mute === undefined)
            throw new Error(`Missing mute state for ${name}`);
        if (!Number.isInteger(node.id))
            throw new Error(`Missing PipeWire node ID for ${name}`);
        sources[name] = {id: node.id, muted: mute};
    }

    if (Object.keys(sources).length !== A50_SOURCES.size)
        throw new Error('Both A50 microphone sources are not available');

    const states = new Set(Object.values(sources).map(source => source.muted));
    const state = states.size > 1 ? 'mixed' : states.has(true) ? 'muted' : 'unmuted';
    return {state, sources};
}

export function microphoneIcon(state) {
    switch (state) {
    case 'muted':
        return 'microphone-disabled-symbolic';
    case 'unmuted':
        return 'microphone-sensitivity-high-symbolic';
    case 'mixed':
        return 'audio-input-microphone-symbolic';
    default:
        throw new Error(`Unknown microphone state: ${state}`);
    }
}

export function toggledMicrophoneMute(state) {
    if (!['muted', 'unmuted', 'mixed'].includes(state))
        throw new Error(`Unknown microphone state: ${state}`);
    return state !== 'muted';
}
