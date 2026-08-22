// Placeholder analysis response, same shape as POST /api/analyse returns.
// coverage is keyed coverage[elementId][patentId] -> { evidence }; a missing
// key means that patent does not read on that element.
const mockData = {
  elements: [
    {
      id: 'e1',
      label: 'Element 1',
      text: 'A wearable band housing an optical heart-rate sensor and a three-axis accelerometer.',
    },
    {
      id: 'e2',
      label: 'Element 2',
      text: 'A controller that samples the sensors at a variable rate selected from the detected activity state.',
    },
    {
      id: 'e3',
      label: 'Element 3',
      text: 'On-device inference of a hydration estimate from galvanic skin response and ambient temperature.',
    },
    {
      id: 'e4',
      label: 'Element 4',
      text: 'A haptic actuator that fires a graded alert pattern encoding the severity of the estimate.',
    },
    {
      id: 'e5',
      label: 'Element 5',
      text: 'Encrypted delta-sync of session summaries to a paired handset over BLE when the link returns.',
    },
    {
      id: 'e6',
      label: 'Element 6',
      text: 'A calibration routine that fits per-user baselines from the first seven days of wear.',
    },
  ],
  patents: [
    {
      id: 'p1',
      number: 'US 9,872,150 B2',
      title: 'Wrist-worn physiological monitoring device',
      assignee: 'Fitbit, Inc.',
    },
    {
      id: 'p2',
      number: 'US 10,314,547 B2',
      title: 'Adaptive sampling of biometric sensors based on activity classification',
      assignee: 'Apple Inc.',
    },
    {
      id: 'p3',
      number: 'US 10,987,024 B1',
      title: 'Haptic notification patterns for physiological thresholds',
      assignee: 'Garmin Switzerland GmbH',
    },
    {
      id: 'p4',
      number: 'US 11,406,310 B2',
      title: 'Secure synchronization of health records to a mobile terminal',
      assignee: 'Samsung Electronics Co., Ltd.',
    },
  ],
  coverage: {
    e1: {
      p1: {
        evidence:
          'Claim 1: "a band configured to be worn about a wrist, the band comprising a photoplethysmographic sensor and an inertial measurement unit including at least three axes of acceleration sensing."',
      },
      p2: {
        evidence:
          'Col. 4, ll. 12-19: "the wearable housing carries the optical emitter/detector pair alongside the accelerometer used for gating."',
      },
    },
    e2: {
      p2: {
        evidence:
          'Claim 7: "selecting, by the processor, one of a plurality of sampling rates for the biometric sensor in response to the activity class output by the classifier."',
      },
    },
    e4: {
      p3: {
        evidence:
          'Claim 3: "driving the haptic actuator with a first pattern when the measured parameter exceeds a first threshold and a second, denser pattern when it exceeds a second threshold."',
      },
    },
    e5: {
      p4: {
        evidence:
          'Claim 1: "transmitting an encrypted incremental record of the monitoring session to the paired mobile terminal upon re-establishment of the short-range wireless link."',
      },
      p1: {
        evidence:
          'Col. 11, ll. 33-41: "summaries buffered on the device are uploaded when the companion application reconnects."',
      },
    },
  },
  uncovered: ['e3', 'e6'],
  suggestions: [
    {
      id: 's1',
      title: 'Claim the hydration inference as the point of novelty',
      reasoning:
        'No searched reference reads on deriving a hydration estimate on-device from galvanic skin response combined with ambient temperature. Draft the independent claim around this element and recite the band, sensors and controller only as the environment they run in.',
      patent: 'p1',
    },
    {
      id: 's2',
      title: 'Recite the seven-day per-user baseline fit as a dependent limitation',
      reasoning:
        'The calibration window is also uncovered. Adding it as a dependent claim gives fallback scope if the hydration claim is rejected over non-patent literature.',
      patent: 'p2',
    },
    {
      id: 's3',
      title: 'Design around adaptive sampling',
      reasoning:
        'Claim 7 of the Apple reference squarely covers rate selection from an activity class. Trigger rate changes from a skin-conductance variance threshold instead, which the claim language does not reach.',
      patent: 'p2',
    },
    {
      id: 's4',
      title: 'Drop graded haptic severity encoding from the claims',
      reasoning:
        'The Garmin reference claims multi-threshold haptic patterns directly. Keep the feature in the specification as an embodiment, but do not claim it.',
      patent: 'p3',
    },
  ],
}

export default mockData
