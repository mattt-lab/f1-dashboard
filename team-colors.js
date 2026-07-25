// Shared team color map — loaded by f1-dashboard.html, f1-drivers.html, and
// f1-constructors.html so all three pages always agree on team colors.
//
// Values are sourced from OpenF1's `drivers` endpoint (team_colour field),
// which mirrors the exact hex F1 itself uses for its live-timing graphics —
// treat it as authoritative and re-sync here if a team's livery changes.
//
// Legacy constructorIds (alphatauri, kick_sauber, sauber) aren't in OpenF1's
// current-season data since those teams were rebranded — keep their last-known
// colors so any historical Jolpica result using the old id still renders sensibly.
const TEAM_COLORS = {
    red_bull:     '#4781D7',
    ferrari:      '#ED1131',
    mercedes:     '#00D7B6',
    mclaren:      '#F47600',
    aston_martin: '#229971',
    alpine:       '#00A1E8',
    williams:     '#1868DB',
    rb:           '#6C98FF',
    haas:         '#9C9FA2',
    audi:         '#F50537',
    cadillac:     '#909090',

    // Legacy ids, kept for historical results predating a team's rebrand
    alphatauri:   '#6692FF',
    kick_sauber:  '#52E252',
    sauber:       '#52E252',
};

const teamColor = id => TEAM_COLORS[id?.toLowerCase()] || '#777';
