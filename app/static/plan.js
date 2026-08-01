/* Calendar plan forms — the Tindeq setup a planned hangboard item carries.
 *
 * Shows the setup fields only for hangboard items, and only the ones the chosen
 * exercise actually uses, mirroring the capture page. Picking an exercise fills
 * in that exercise's default protocol so a planned session is one click away
 * from being startable.
 */

const TIMER_EXERCISES = ["repeaters", "max_hang"];
const BASELINE_EXERCISES = ["mvc_test", "rfd_test"];

const field = (form, name) => form.querySelector(`[name="${name}"]`);
const show = (form, selector, visible) =>
    form.querySelectorAll(selector).forEach(el => el.hidden = !visible);

function syncForm(form) {
    const isHangboard = field(form, "item_type").value === "hangboard";
    show(form, ".rx-group", isHangboard);
    if (!isHangboard) return;

    const ex = field(form, "exercise_type").value;
    const isTimer = TIMER_EXERCISES.includes(ex);
    const isBaseline = BASELINE_EXERCISES.includes(ex);
    show(form, ".rx-any", !!ex);
    show(form, ".rx-timer", isTimer);
    show(form, ".rx-sets", isTimer || isBaseline);
    show(form, ".rx-repeaters", ex === "repeaters");
    // Sets/rest are shared between timer and baseline exercises under different names.
    form.querySelectorAll(".rx-sets label").forEach(el => {
        el.textContent = isBaseline ? el.dataset.baseline : el.dataset.timer;
    });
}

function applyDefaults(form) {
    const ex = field(form, "exercise_type").value;
    const d = window.EXERCISE_DEFAULTS[ex];
    if (d) {
        field(form, "on_seconds").value = d.on_off[0];
        field(form, "off_seconds").value = d.on_off[1];
        field(form, "target_sets").value = d.sets_reps[0];
        field(form, "target_reps").value = d.sets_reps[1];
        if (!field(form, "set_rest_s").value) field(form, "set_rest_s").value = 180;
    }
    const b = window.BASELINE_DEFAULTS[ex];
    if (b) {
        field(form, "target_sets").value = b.attempts;
        field(form, "set_rest_s").value = b.rest_s;
    }
}

document.querySelectorAll("form.plan-form").forEach(form => {
    syncForm(form);
    field(form, "item_type").addEventListener("change", () => syncForm(form));
    field(form, "exercise_type").addEventListener("change", () => {
        applyDefaults(form);
        syncForm(form);
    });
});
