> **NOTICE — AI-GENERATED DRAFT FOR ATTORNEY REVIEW.** This document was generated
> by an automated patent-clearance and drafting workflow. It has **not** been filed
> with the USPTO or any other patent office, it is **not** a legal opinion, and it
> must be reviewed, corrected and re-scoped by a licensed patent practitioner
> before any filing or public disclosure. The prior-art record behind this draft is
> **partial**: only a CPC classification sweep and a non-patent-literature sweep
> completed; the USPTO full-text search, the Google Patents semantic/citation sweep
> and the competitor-portfolio sweep (Noonlight, ADT/SoSecure, RapidSOS, Life360,
> bSafe, Flare, Titan, SafeUP and others) were **not** completed. No foreign patent
> rights were searched. Additional blocking claims and additional novelty-defeating
> disclosures may exist. Legal statuses quoted below were read on Google Patents on
> 2026-08-22 and must be re-confirmed on USPTO Patent Center before commercial
> reliance.

# Serverless-Proximity Peer Rescue Network: Broadcast-to-Region SOS with On-Device Isochrone Gating, Attested-Credential Eligibility and Cryptographically Revocable Identity Reveal

## Technical Field

The invention relates to mobile applications for personal safety, to
privacy-preserving location services, and to decentralised proximity networking.
More particularly, it relates to distributed systems in which an emergency
assistance request ("SOS") is disseminated to peer mobile devices without any
server holding, monitoring or acting upon per-device geographic location, in
which recipient eligibility is enforced by cryptographic credential proofs
evaluated at alert time, and in which the disclosure of a requesting user's
identity and live position to a responding device is controlled — and revoked —
by ephemeral key material rather than by application-level display rules.

## Background

Peer-assistance personal-safety systems are well populated in the art. The
common architecture is a central server that continuously tracks the geographic
position of every enrolled user, receives a distress trigger from one user's
device, computes which other user devices are within a predetermined vicinity of
the distress location, and pushes the alert to that selected subset.

- **US 10,445,959 B2** (Kerning, priority 2014-07-28, granted 2019-10-15, in
  force) claims, in independent claim 1, exactly this architecture: client
  devices configured for *continuously transmitting* their respective geographic
  location to a server; the *server continuously monitoring* the geographic
  location of each client device; a client device selectively transmitting an
  alert to the server; the server identifying which device transmitted the alert;
  and *the server transmitting a message to a selective one or more client
  devices being in proximity to* the alerting device.
- **US 9,454,889 B2** (Kerning) adds, on the same continuous-server-tracking
  base, medical dispatch, a pre-recorded voice call, a fee for the alert and a
  reward to the first responder to arrive.
- **US 2025/0294350 A1** is a pending continuation in the same Kerning family.
- **US 2014/0118140 A1** (Amis, published 2014-05-01, abandoned) discloses a
  server that, on receipt of a distress signal with location data, identifies
  *pre-screened* opt-in volunteers whose periodically-reporting devices lie
  within a predetermined vicinity of the distress location, transmits the request
  to them, displays the distress location on a map on the volunteer's device, and
  receives an acceptance signal.
- **US 9,414,212 B2** (Nokhoudian, expired for fee) discloses server-routed
  assistance requests with responder identity, distance and ratings shown to the
  requester, and notification of responders at increasing distances until one
  accepts.
- **US 9,820,120 B2** (deCharms) requires a two-way audiovisual teleconference
  with concurrent upload to remote persistent storage.
- **US 9,247,408 B2** and **US 10,863,317 B2** (Patrocinium / Lost Mountain
  Ranch) define a server-side geo-fence with plural proximity zones around an
  incident, receive live locations of user devices, and determine which devices
  are inside which zone for display on an administrator screen.
- **US 11,527,149 B2** (Outsmart) has a community server remotely activating
  devices of private security systems near the requester.
- **US 12,452,359 B2** (Titan) recites a location-sharing short link and
  emergency-source sighting information placed on an administrator map.
- **US 11,138,855 B2** and **US 12,283,170 B2** (Avive) select a set of nearby
  responders on a server and send each a nearby-incident message, in a
  cardiac-arrest/defibrillator context.
- **WO 2015/036926 A2** (Amrita Vishwa Vidyapeetham, ceased) relays a wearable
  trigger through a central monitoring server to emergency contacts and nearby
  registered responder devices.

Non-patent literature discloses the product-level feature set. **SafeUP** (public
2021-03-14) operates a women-only network with video identity verification and
human verifiers, a live map of nearby verified members and guardians with their
photographs, and guardians within about 500 m who physically attend. **GoodSAM**
alerts identity-verified and qualification-checked responders within a
service-configured radius (typically 500 m), offers Accept/Reject, reports
"On scene"/"With patient" status, tells a responder which other responders
accepted, and removes the incident address when the case completes. **Usalama**
(press of 2017-12-22) broadcasts a distress signal to "every Usalama user within
200 metres". **Jayaram et al.**, ICRDICCT'25, broadcast an SOS to all registered
volunteers within 500 m of the GPS fix taken at trigger, with accept/dismiss and
a responder group chat. **Ally** (ICCSP 2020) crowdsources a distress signal to
all nearby app users within a kilometre. **PulsePoint Respond** (public since
2012) performs proximity broadcast to tiered, credential-gated responder classes
with the victim location on a responder map. **DIA(light)** (IRJET, April 2017)
sends an SOS notification with the user's current location to nearby app users
independently of the emergency-contact path. **P2P Models** (2021-03-31)
catalogues "sending alerts to app users that are geographically near" and
"visualizing a user's information, if they have sent an alert" as features
already standard in the field.

Three deficiencies are common to all of the above.

*First, the architecture requires the service operator to hold a live map of
where its users are.* Continuous position reporting and server-side monitoring
create a high-value tracking database, are difficult to reconcile with data
minimisation obligations, and make the operator a single point of compromise and
of compelled disclosure. They are also the elements on which the broadest
in-force claim in the field reads.

*Second, eligibility to receive an alert is an account-state flag.* Whether a
recipient is a "verified" member, a trained responder, or a pre-screened
volunteer is decided once at enrolment and thereafter carried by a session or
account record. A stale, shared, cloned or revoked account, or a device that has
changed hands, continues to receive alerts; nothing at alert time proves that the
holder of the device is the credentialed, live human to whom the credential was
issued.

*Third, proximity is a straight-line radius computed by the server, and the
disclosure of the requester's identity and position is a display rule.* A metric
circle admits devices separated from the requester by a river, a motorway, a rail
cutting, a wall or a locked gate — devices that cannot traverse to the requester
in any useful time — while a device that has reported a fabricated GPS fix is
admitted outright. Once the alert payload has been delivered in the clear to such
a device, withdrawal of access is cosmetic: the art removes the incident address
from the responder's screen at case completion, but the plaintext has already
been released, and nothing stops delivery of *further* updates the moment the
responder ceases to be eligible or leaves the area.

A need therefore exists for a peer-rescue mechanism in which the transport
performs no proximity computation and holds no per-device location, in which
eligibility is proved cryptographically per alert, in which reachability is
evaluated on the device that owns the location against a traversable street
graph, and in which the requester's identity and live track are released under
key material whose continued delivery is itself the enforcement mechanism.

## Summary of the Invention

In one aspect, a requesting device generates a per-alert symmetric alert key,
encrypts an alert envelope containing the requester's coordinates and a
capability-wrapping public key under that key, and publishes the envelope to a
coarse region-scoped publish/subscribe topic — or to an open claimable alert
queue that devices poll. The topic is identified by a rotating, opaque
geohash-bucket token of coarse granularity (approximately 1 km) that is
unlinkable across rotations. No device reports its geographic position to the
backend, the backend never monitors device locations, and the backend performs no
selection, ranking or targeting of recipients by proximity to the alerting
device: it forwards an opaque ciphertext to every subscriber of a bucket token.
The envelope is self-contained and signed, so it can equally be relayed
device-to-device over a short-range mesh when the requester has no usable data
connection.

Each subscribed recipient device decides for itself, entirely locally, whether it
is eligible and reachable. Eligibility is a cryptographic mechanism, not an
account flag: the recipient device holds a revocable verifiable credential
asserting an operator-configured attribute predicate, and must generate a *fresh*
zero-knowledge predicate proof over that credential, together with a liveness
re-attestation of the human holder and a hardware device-key attestation, in
order to obtain the capability that decrypts the alert payload. Reachability is a
pedestrian walk-time isochrone (approximately 3 minutes by default) computed on
the recipient device from the requester's coordinates over an offline
street-and-barrier graph, so rivers, motorways, walls and closed gates exclude
devices that a straight-line radius would include, and the inclusion decision is
made on the device that owns the location rather than by a server that is told
the location.

Before the requester's name, photograph and live track are unwrapped, the
recipient device must additionally produce a physical-presence witness — BLE, UWB
or Wi-Fi Aware ranging, or an ambient RF/audio co-witnessing measurement shared
with the requester's device or with other in-zone devices — so a device reporting
a fabricated position cannot enter the responder set.

Identity and live position are then distributed as a stream re-keyed on a short
interval. A responder receives each successive key only while it re-proves, per
interval, that its credential is unrevoked, that its holder is live, and that it
remains inside the *recomputed* isochrone. Crossing out of the zone, revocation
of the credential, or closure of the alert simply stops key delivery, which
renders any retained ciphertext undecryptable and triggers deletion of the
plaintext copy held in volatile memory. Every unwrap of the requester's identity
is written to a tamper-evident, hash-chained log that the requester can read
afterwards, identifying which responder saw what and for how long.

Recruitment escalates in stages tied to accept state: the alert remains confined
to the narrow isochrone while the accepted-responder count meets a threshold and
widens to successive rings (approximately 3, 6 then 10 minutes, and thereafter to
an optional emergency-service or trusted-contact fallback) only when accepts fall
below it. Responders are de-duplicated, hand-off is explicit if a responder
aborts, accept and en-route state is shared among the requester and the accepted
responders, and arrival is confirmed by a mutual short-range handshake in which
the two devices exchange signed proximity attestations, closing the alert
automatically on confirmed contact.

## Detailed Description

### Figures

**FIG. 1** is a system block diagram of an embodiment. It shows a requesting
device (100) comprising an alert composer (102), a per-alert key generator (104),
a mesh relay interface (106) and an audit-log reader (108); an untargeted
publish/subscribe transport (200) comprising a bucket-token registry (202) that
stores only rotating opaque tokens and their current subscriber connections, and
a fan-out engine (204) that forwards opaque ciphertexts and holds no per-device
geographic location and no proximity logic; a plurality of recipient devices
(300a-300n) each comprising a credential wallet (302), a zero-knowledge prover
(304), a liveness and device-key attestation module (306), an offline pedestrian
graph store (308), an on-device isochrone engine (310), a presence-witness module
(312), a rolling key client (314) and an ephemeral reveal store (316); a
credential issuer and revocation registry (400); and a tamper-evident audit
service (500) holding a hash-chained append-only log.

**FIG. 2** is a message-sequence diagram of one alert lifecycle: trigger; key
generation; envelope publication to bucket token *B*; fan-out to all subscribers
of *B*; per-device local isochrone evaluation; predicate-proof generation and
capability unwrap by eligible-and-reachable devices only; presence-witness
exchange; identity reveal; accept; rolling re-key intervals with per-interval
re-proof; zone exit and key-delivery cessation for one responder; rendezvous
handshake; alert closure and plaintext deletion.

**FIG. 3** is a map diagram contrasting a 200 m straight-line circle with a
3-minute pedestrian isochrone computed over a street graph interrupted by a
river and a motorway. Device (300a) lies inside the circle but on the far bank,
with the nearest bridge 900 m away, and is excluded by the isochrone; device
(300b) lies outside the circle but on a continuous footpath and is included.

**FIG. 4** is a state diagram of the rolling capability: `SUBSCRIBED` →
`ELIGIBLE` (proof valid) → `IN_ZONE` (isochrone satisfied) → `CORROBORATED`
(presence witness accepted) → `REVEALED` → `ACCEPTED` → `EN_ROUTE` →
`ARRIVED`/`CLOSED`, with a transition from any post-`REVEALED` state to
`REVOKED` on failure of any per-interval re-proof, on credential revocation, or
on alert closure, and with `REVOKED` unconditionally entering `WIPED`.

**FIG. 5** is a diagram of staged escalation showing three nested isochrone rings
and the accept-count threshold test evaluated at each stage boundary.

**FIG. 6** is a data-structure diagram of the alert envelope: an unencrypted
header carrying the bucket token, the alert identifier, a monotonic sequence
number, a publication timestamp and a publisher signature over the whole
envelope; and a ciphertext body carrying the requester's coordinates, the
requester's identity block, the capability-wrapping public key, the operator
predicate identifier, the isochrone parameters and the rolling-key stream
descriptor.

### First embodiment: urban deployment of a peer-rescue network

**Provisioning.** On enrolment, a user is issued a verifiable credential by the
issuer (400). The credential asserts an operator-configured attribute set; in the
launch configuration of this embodiment the configured predicate is
verified-woman status, but the predicate is a deployment parameter and the
mechanism is indifferent to which attribute is configured — an operator may
configure trained-responder status, employment status, or any conjunction of
attributes. The credential is stored in the wallet (302) bound to a
hardware-backed key attested by the module (306), together with a revocation
witness that the device refreshes from the registry (400). The device also
downloads an offline pedestrian graph extract for its regions of use into the
store (308), typically a few tens of megabytes per city, comprising footway,
crossing, stair and barrier edges with traversal costs, and refreshes it
periodically.

**Subscription without location disclosure.** The device computes the coarse
geohash cell (in this embodiment a five-character geohash, of roughly 1 km
granularity) containing its current position, and derives an opaque bucket token
as a keyed hash of the cell identifier and a rotation epoch that advances on a
fixed schedule, for example every fifteen minutes. It subscribes to that token
at the registry (202). Because the token is opaque and re-derived on each epoch,
the transport can neither invert it to a geographic cell nor link a subscriber
across rotations; the device pads its subscription set with a small number of
decoy tokens for neighbouring cells so that the subscribed set is not a
single-cell fingerprint. The transport therefore holds, at most, a coarse
ephemeral token per connection, and never a per-device geographic location. No
device continuously transmits its geographic position to the transport, and the
transport never monitors device positions.

**Trigger and publication.** The requester triggers an SOS. The generator (104)
creates a per-alert symmetric key *K0* and a capability-wrapping key pair. The
composer (102) builds the envelope of FIG. 6 and encrypts the body under *K0*.
The device publishes the envelope on the bucket token for its own cell (and,
optionally, on the tokens of the adjacent cells). It does *not* transmit its
position to the transport, does not ask the transport to find nearby users, and
the transport does not identify who is near whom. In parallel, the same signed
envelope is offered over BLE and Wi-Fi Aware to any device in short range, which
re-offers it with a decremented hop budget, so that the alert propagates by mesh
relay when the requester has no usable data connection; duplicate envelopes are
suppressed on the alert identifier and sequence number.

**Local eligibility and reachability gating.** A recipient device receives the
opaque ciphertext as a silent, low-priority notification. It first performs the
gate that requires no plaintext: the header is signed by a publisher whose
authorisation to publish is itself credential-rate-limited, so unsigned or
over-rate envelopes are dropped without user-visible effect. To learn the
requester's coordinates the device generates, in the prover (304), a fresh
zero-knowledge predicate proof over its credential — disclosing that the
predicate holds and that the credential is unrevoked, but not the credential
itself nor any identifier — bound to a challenge derived from the alert
identifier and the current epoch, and accompanied by a liveness re-attestation
(a platform face or fingerprint liveness assertion) and a device-key attestation.
The proof and attestations are presented to a capability service, which is unable
to read the alert body, and which returns the wrapped capability that unwraps
*K0*. Only a device that presents a valid, fresh proof obtains the capability;
because the proof is generated per alert and bound to a liveness assertion and an
attested hardware key, a stale session, a shared or exported credential, a cloned
device image or a revoked credential yields nothing. The device then decrypts
only the coordinate and parameter portion of the body, and the isochrone engine
(310) computes, over the offline graph (308), the set of graph nodes reachable on
foot from the requester's coordinates within the configured walk time (3 minutes
by default, at a configured pedestrian speed), and tests whether its own position
lies within the reachable polygon. The engine runs a bounded Dijkstra expansion
and completes in well under 100 ms on a contemporary handset. A device that fails
the test discards the decrypted coordinates, surfaces nothing to the user, and
does not proceed. The inclusion decision is thus taken on the device that owns
the location, and no entity other than that device learns whether it was inside.

**Presence corroboration before reveal.** A device that passes the isochrone test
must, before the requester's identity block is unwrapped, produce a presence
witness through the module (312): a signed BLE, UWB or Wi-Fi Aware ranging
exchange with the requester's device, or, where the two devices are not yet in
radio range, an ambient co-witnessing measurement — a coarse fingerprint of
observed RF beacons or of an ambient-audio digest — that matches, within a
tolerance, a corresponding measurement contributed by the requester's device or
by two or more other corroborated in-zone devices. The witness is short-lived and
bound to the alert challenge. A device that reports a fabricated position and is
not physically in the area cannot produce a matching witness and is refused the
identity capability, though it may still be shown a degraded, identity-free
notice.

**Scoped reveal and rolling revocation.** On corroboration, the device receives
the ephemeral per-alert capability token that decrypts the requester's identity
block — name and photograph — into the reveal store (316), which is
memory-resident and never written to durable storage. Live position updates are
published as a stream whose key ratchets every interval (5 seconds in this
embodiment), *Ki+1* being derivable only from key material delivered for that
interval. The rolling key client (314) obtains *Ki+1* only by presenting, for
that interval, a refreshed revocation-checked predicate proof, a liveness
assertion within a configured recency window, and an assertion that the device
remains inside the isochrone recomputed from the requester's *latest* position.
Any failure — the responder crosses out of the zone, the credential is revoked at
the registry (400), the liveness window lapses, or the requester closes the alert
— results simply in no further key being delivered. Retained ciphertext for
subsequent intervals is therefore undecryptable, and the client additionally
zeroises the reveal store (316) and the current plaintext track. Withdrawal of
access is thus a consequence of the key schedule rather than of a display rule,
and does not depend on the responder device honouring a delete instruction for
*future* data; the residual risk that a compromised device retains what it has
already decrypted is addressed by audit rather than by recall.

**Audit.** Each capability unwrap and each interval key delivery is recorded by
the audit service (500) as an entry in a hash-chained append-only log — responder
pseudonym, alert identifier, the class of data unwrapped, and the interval range
— with periodic signed checkpoints, so that entries cannot be removed or
back-dated without detection. The requester reads the log through (108) after the
alert, and can see which responders saw her identity and for how long.

**Escalation, de-duplication and hand-off.** A responder that accepts publishes a
signed accept to the alert's ephemeral group, which is shared with the requester
and with the other accepted responders together with en-route state. Accepts are
de-duplicated on the responder's per-alert pseudonym so that one holder cannot
occupy several slots. The requester's device evaluates, at each stage boundary,
whether the accepted count meets the configured threshold; only if it does not
does it re-publish the envelope with a widened isochrone parameter (6 minutes,
then 10 minutes), and only after the widest ring fails does it offer the optional
fallback to emergency services or to trusted contacts. If a responder aborts, its
slot is released and hand-off is announced to the group, which may trigger an
immediate re-evaluation of the escalation stage.

**Rendezvous and closure.** On approach, the requester's device and the arriving
responder's device perform a mutual short-range handshake: each signs a proximity
attestation over the alert identifier, the measured range and a fresh nonce, and
verifies that the counterparty's attestation is signed by the same per-alert
pseudonym that accepted. Confirmed mutual attestation both assures the requester
that the person arriving is the credentialed responder who accepted, and closes
the alert automatically, which stops all key delivery and triggers the wipe on
every responder device.

### Second embodiment: claimable alert queue

In a variant, the transport exposes no push channel. The requester's device posts
the encrypted envelope to an open queue partitioned by rotating bucket token, and
recipient devices poll their partitions on a short schedule and *claim* alerts
they have locally determined themselves eligible for and reachable to. No step of
a server transmitting a message to devices in proximity to the alerting device
occurs at all; the server neither knows nor can compute which claimant is near.
All gating, revealing, revocation, escalation and rendezvous mechanics are as in
the first embodiment.

### Variations

The predicate configured in the credential is a deployment parameter. Geohash
granularity, rotation period, isochrone durations, re-key interval, accept
threshold and hop budget are configuration values. The isochrone may be replaced
by any traversable-reachability computation over the offline graph, including
wheelchair-accessible or cycling cost models, and may incorporate time-of-day
edge availability such as closed gates or parks. The presence witness may use any
short-range radio or ambient-sensing modality. The audit log may be held on a
transparency log or a permissioned ledger. The capability service may be
implemented as a threshold or oblivious service so that it learns neither the
identity of the prover nor the content of the alert.

## Claims

1. A method of disseminating an emergency assistance request among peer mobile
   devices, the method comprising: generating, at a requesting device, a
   per-alert content key and encrypting under the per-alert content key an alert
   envelope comprising a geographic position of the requesting device and an
   identity payload of a requesting user; publishing the encrypted alert envelope
   from the requesting device to a region-scoped dissemination channel identified
   by a rotating opaque coarse-geographic-bucket token to which recipient devices
   subscribe, wherein no recipient device continuously transmits its geographic
   position to a server of the dissemination channel, no server of the
   dissemination channel monitors the geographic position of any recipient
   device, and no server of the dissemination channel selects, ranks or targets
   recipients by proximity to the requesting device; receiving the encrypted
   alert envelope at a recipient device subscribed to the bucket token;
   generating at the recipient device, responsive to the encrypted alert
   envelope, a fresh zero-knowledge predicate proof over a revocable verifiable
   credential held by the recipient device together with a liveness
   re-attestation and a device-key attestation, and obtaining a decryption
   capability for the alert envelope only on validity of the proof and the
   attestations; computing, locally at the recipient device and using the
   decrypted geographic position of the requesting device, a pedestrian walk-time
   isochrone over an offline street-and-barrier graph stored at the recipient
   device, and determining locally at the recipient device whether a position of
   the recipient device lies within the isochrone; suppressing the emergency
   assistance request at the recipient device when the position of the recipient
   device does not lie within the isochrone; obtaining at the recipient device,
   when the position of the recipient device lies within the isochrone, a
   corroborating physical-presence witness derived from short-range
   device-to-device ranging or ambient co-witnessing, and decrypting the identity
   payload into volatile memory of the recipient device under an ephemeral
   per-alert capability token only on acceptance of the physical-presence
   witness; and distributing subsequent live-position updates of the requesting
   device as a stream re-keyed at successive intervals, wherein the recipient
   device obtains the key for each successive interval only upon re-proving, for
   that interval, that the verifiable credential is unrevoked, that the liveness
   re-attestation is current, and that the position of the recipient device
   remains within the isochrone recomputed from a latest position of the
   requesting device, such that cessation of key delivery on failure of any said
   re-proving, on revocation of the credential, or on closure of the emergency
   assistance request renders retained ciphertext of the stream undecryptable and
   triggers deletion of the decrypted identity payload from the volatile memory.

2. The method of claim 1, wherein the region-scoped dissemination channel is a
   claimable alert queue that recipient devices poll and from which an eligible
   recipient device claims the encrypted alert envelope, such that no server
   transmits the emergency assistance request to a device selected as being in
   proximity to the requesting device.

3. The method of claim 1, wherein the rotating opaque coarse-geographic-bucket
   token is derived as a keyed function of a coarse geohash cell of approximately
   one kilometre granularity and of a rotation epoch, and is unlinkable across
   successive rotation epochs.

4. The method of claim 3, wherein the recipient device additionally subscribes to
   one or more decoy bucket tokens of neighbouring coarse geohash cells.

5. The method of claim 1, wherein the attribute predicate proved by the
   zero-knowledge predicate proof is configured by an operator of the
   dissemination channel, and wherein the recipient device proves that the
   predicate holds without disclosing the verifiable credential or an identifier
   of the recipient user.

6. The method of claim 1, wherein the zero-knowledge predicate proof is bound to
   a challenge derived from an identifier of the emergency assistance request, so
   that a proof generated for one emergency assistance request cannot obtain the
   decryption capability for another.

7. The method of claim 1, wherein the verifiable credential is bound to a
   hardware-backed key of the recipient device and the device-key attestation
   attests that binding, such that a cloned copy of the credential on another
   device cannot obtain the decryption capability.

8. The method of claim 1, wherein the pedestrian walk-time isochrone has a
   default traversal duration of approximately three minutes and is computed by a
   bounded shortest-path expansion over footway, crossing, stair and barrier
   edges of the offline street-and-barrier graph.

9. The method of claim 8, wherein a device separated from the requesting device
   by a barrier edge of the offline street-and-barrier graph is excluded from
   surfacing the emergency assistance request notwithstanding that a
   straight-line distance between the device and the requesting device is less
   than a traversable distance of a device that is included.

10. The method of claim 1, wherein the corroborating physical-presence witness
    comprises a signed ranging exchange over Bluetooth Low Energy, ultra-wideband
    or Wi-Fi Aware with the requesting device.

11. The method of claim 1, wherein the corroborating physical-presence witness
    comprises an ambient radio-frequency or audio fingerprint measurement that
    matches, within a tolerance, a corresponding measurement contributed by the
    requesting device or by at least two further corroborated recipient devices
    within the isochrone.

12. The method of claim 1, wherein a recipient device that fails to obtain the
    corroborating physical-presence witness is refused the ephemeral per-alert
    capability token and is presented with an identity-free notice of the
    emergency assistance request.

13. The method of claim 1, wherein the successive intervals of the re-keyed
    stream are of a duration of approximately five seconds, and the key for each
    successive interval is not derivable from key material delivered for
    preceding intervals.

14. The method of claim 1, further comprising writing each obtaining of the
    decryption capability and each delivery of an interval key as an entry of a
    hash-chained append-only audit log with periodic signed checkpoints, the
    entry identifying a per-alert pseudonym of the recipient device, a class of
    data decrypted and a range of intervals.

15. The method of claim 14, further comprising presenting the audit log to the
    requesting user after closure of the emergency assistance request, indicating
    which recipient devices decrypted the identity payload and for how long.

16. The method of claim 1, further comprising evaluating at the requesting device
    a count of recipient devices that have published a signed acceptance, and
    re-publishing the encrypted alert envelope with a widened isochrone traversal
    duration only when the count is below a configured threshold.

17. The method of claim 16, wherein the widened isochrone traversal durations
    comprise successive rings of approximately six minutes and approximately ten
    minutes, followed, only on continued failure to meet the threshold, by a
    fallback notification to an emergency service or to a trusted contact.

18. The method of claim 16, further comprising de-duplicating acceptances on a
    per-alert pseudonym of the accepting recipient device, and announcing a
    hand-off to remaining accepted recipient devices when an accepted recipient
    device aborts.

19. The method of claim 1, further comprising sharing an acceptance state and an
    en-route state of each accepted recipient device with the requesting device
    and with the other accepted recipient devices.

20. The method of claim 1, further comprising performing, on arrival, a mutual
    short-range handshake in which the requesting device and the accepted
    recipient device each exchange a proximity attestation signed over an
    identifier of the emergency assistance request, a measured range and a fresh
    nonce, verifying that the counterparty attestation is signed by the same
    per-alert pseudonym that published the acceptance, and closing the emergency
    assistance request automatically on successful mutual verification.

21. The method of claim 1, further comprising relaying the encrypted alert
    envelope from the requesting device directly to a further device over a
    short-range radio link, and re-relaying the encrypted alert envelope from the
    further device with a decremented hop budget, such that the emergency
    assistance request propagates to eligible recipient devices while the
    requesting device has no usable wide-area data connection.

22. The method of claim 1, wherein the encrypted alert envelope is delivered to
    the recipient device as a silent notification whose payload is decryptable
    only by a device obtaining the decryption capability, and wherein publication
    of encrypted alert envelopes is rate-limited per publishing credential.

23. A recipient mobile device comprising a credential wallet storing a revocable
    verifiable credential, a zero-knowledge prover, a liveness and device-key
    attestation module, a store holding an offline pedestrian street-and-barrier
    graph, an isochrone engine, a presence-witness module, a rolling key client
    and a volatile reveal store, the device being configured to subscribe to a
    region-scoped dissemination channel under a rotating opaque
    coarse-geographic-bucket token without transmitting its geographic position
    to a server of the channel, and to perform the receiving, proof-generating,
    isochrone-computing, suppressing, corroborating, decrypting and interval
    re-proving steps of claim 1.

24. A non-transitory computer-readable medium storing instructions that, when
    executed by a processor of a mobile device, cause the mobile device to
    perform the receiving, proof-generating, isochrone-computing, suppressing,
    corroborating, decrypting and interval re-proving steps of claim 1.

## Abstract

An emergency request is disseminated among peer mobile devices without any server
holding device locations or selecting recipients. A requesting device
encrypts an envelope carrying its position and identity under a per-alert key and
publishes it to a region-scoped channel identified by a rotating opaque coarse
geohash-bucket token. Each subscribed device qualifies itself locally: a fresh
zero-knowledge predicate proof over a revocable verifiable credential, with
liveness and device-key attestations, yields the decryption capability, and a
pedestrian walk-time isochrone computed over an offline street-and-barrier graph
on the device holding the location decides inclusion. Identity is unwrapped into
volatile memory under an ephemeral capability only after a short-range ranging or
ambient co-witnessing presence witness. Live position is re-keyed each interval,
the next key arriving only while the device re-proves credential validity,
liveness and continued presence, so zone exit, revocation or closure revokes
disclosure cryptographically and triggers deletion. Reveals are logged
tamper-evidently.

## Prior Art Considered

Each reference below was reviewed during clearance. For each, the reason it does
not read on independent claim 1 is given. Legal statuses are as read on
2026-08-22.

### Patents and published applications

| Reference | Status | Why it does not read on claim 1 |
| --- | --- | --- |
| **US 10,445,959 B2** — Kerning, "Security and public safety application for a mobile device with audio/video analytics and access control authentication", priority 2014-07-28, granted 2019-10-15 | Active, expiry 2035-07-28 | Claim 1 requires client devices *continuously transmitting* geographic location to a server, the *server continuously monitoring* each device's location, and the *server transmitting a message to a selective one or more client devices being in proximity to* the alerting device. Claim 1 of the present application affirmatively excludes all three: recipient devices never continuously report position to the channel server, the server never monitors device locations, and the server performs no proximity selection, ranking or targeting — dissemination is untargeted fan-out to subscribers of an opaque coarse bucket token, and every proximity determination is made on the recipient device from an on-device isochrone. Kerning is also silent on per-alert zero-knowledge credential proofs, walk-time isochrones, presence corroboration, and interval re-keyed revocable identity disclosure. |
| **US 2025/0294350 A1** — pending continuation in the Kerning family, filed 2025-04-02 | Pending; claims not fixed | Cannot presently be read on: no allowed claims. Flagged for docketing and continuous monitoring for claims drafted toward verified-responder proximity broadcast; this draft's claim 1 is deliberately anchored on server-blind fan-out, on-device isochrone gating, per-alert zero-knowledge eligibility and rolling-key revocation, none of which is disclosed in the family's specification as filed. |
| **US 9,454,889 B2** — Kerning, "Security and public safety application for a mobile device" | Active to 2035 | Claim 1 requires continuous server-side location transmission plus provision of directions to proximal devices, a medical-dispatch path, a pre-recorded voice call, a fee for the alert and a reward paid to the first responder to arrive. None of these is present, and the continuous-server-location and server-proximity elements are excluded as above. |
| **US 2014/0118140 A1** — Amis, "Methods and systems for requesting the aid of security volunteers using a security network", published 2014-05-01 | Abandoned — not assertable; prior art only | Claims a *server* that receives the distress signal with location data and identifies pre-screened volunteers *within a predetermined vicinity* whose devices periodically report location. Claim 1 here has no server-side identification of in-vicinity recipients and no periodic device location reporting; eligibility is a per-alert cryptographic proof rather than server-held pre-screening, and vicinity is an on-device traversable-reachability isochrone rather than a server-evaluated predetermined vicinity. Amis discloses no cryptographic eligibility binding, no presence corroboration and no revocable keyed disclosure. |
| **US 9,414,212 B2** — Nokhoudian, "Community emergency request communication system" | Expired — fee related; not assertable | Requires server routing of the request to a responder and display, on the requester's device, of responder identity, distance and mutual feedback-rating information; claim 3 notifies responders at increasing distances. Rating-based trust is not credential-proof eligibility, distance rings are not traversability isochrones, and there is no per-alert proof, no presence witness and no keyed revocation. |
| **US 9,820,120 B2** — deCharms, "Mobile security technology" | Active to 2034 | Requires a two-way audiovisual teleconference transmitting the device's location and concurrent upload to remote persistent storage, with responder selection performed on the basis of user/responder location, rating, or a predefined list. The present claim has no teleconference, no remote persistent upload, and no responder selection by any party other than each recipient device itself. |
| **US 9,247,408 B2** — Patrocinium / Lost Mountain Ranch, "Interactive emergency information and identification" | Active | Requires a processor to define a geo-fence with plural proximity zones around the incident, to *receive live locations of a plurality of user devices*, to determine which are inside which zone, and to display them. Claim 1 here has no recipient of live device locations and no administrator display; the reachability zone is computed on and consumed by the recipient device only. |
| **US 10,863,317 B2** — same family | Active | Additionally requires sensor-derived incident determination and a geo-fence whose shape follows a geographical feature defined server-side. Not practised; the isochrone is derived from graph traversability on the recipient device, not from a server-defined feature-following fence. |
| **US 11,527,149 B2** — Outsmart, "Emergency alert system" | Active | Requires a community security server that receives the requester's current location and remotely activates devices of nearby private security systems by geographic proximity to that location. No server here receives a location for proximity purposes and no third-party security infrastructure is activated. |
| **US 12,452,359 B2** — Titan, "Community safety, security, health communication and emergency notification system" | Active | Requires obtaining user location via a location-sharing link, obtaining emergency-source sighting information, and placing the emergency on an administrator/responder map interface. None of these limitations is present. |
| **US 11,138,855 B2**, **US 12,283,170 B2** — Avive Solutions, "Responder network" | Active | Claims *selecting a set of nearby responders* server-side and sending each a nearby-incident message, in defibrillator/AED and PSAP-dispatcher-widget contexts. Server-side selection of nearby responders is the element affirmatively excluded here; no AED or dispatcher widget is involved. |
| **WO 2015/036926 A2** — Amrita Vishwa Vidyapeetham, "Networked devices and methods for personal safety and security" | Ceased; no granted US member found | Device/central-monitoring-server centric: a trigger sends geo-location and audio/video to a central monitoring server that notifies contacts and nearby registered responders. The present claim has no central monitoring server, no audio/video upload, and no server-side notification of nearby responders. |

### Non-patent literature (novelty/obviousness only; no infringement risk)

| Reference | Public since | Why it does not read on claim 1 |
| --- | --- | --- |
| **SafeUP** (SafeUP Ltd., Tel Aviv) | 2021-03-14/16 | Discloses women-only membership enforced by video identity verification and human verifiers, a live map of nearby verified members and guardians with photographs, and guardians within about 500 m who physically attend. Verification is an enrolment-time human process producing an account flag, not a per-alert zero-knowledge predicate proof with liveness and device-key attestation gating decryption; the server holds member locations and computes the nearest guardians; proximity is a metric radius, not an on-device walk-time isochrone; there is no presence corroboration, no interval re-keyed identity stream and no cryptographic revocation or tamper-evident reveal audit. |
| **GoodSAM Responder platform** | Commercially deployed | Alerts identity-verified, qualification-checked responders within a service-configured radius from server-held real-time geolocation, with Accept/Reject, On-scene/With-patient status, notice of which other responders accepted, and removal of the incident address at case completion. Server-side proximity alerting from server-held locations is excluded by claim 1; qualification checking is account state, not a per-alert proof; address removal at completion is a display rule, whereas claim 1 requires interval key delivery conditioned on continuous re-proof such that retained ciphertext becomes undecryptable. |
| **Usalama** (press 2017-12-22) | 2017-12-22 | Broadcasts a distress signal to "every Usalama user within 200 metres", plus emergency services and next of kin. Literally discloses the 200 m straight-line figure, which is deliberately not relied on here; discloses no on-device graph-based reachability, no credential proof, no presence witness, no keyed revocation. |
| **Jayaram et al., ICRDICCT'25** | 2025 | SOS to all registered volunteers within 500 m of the GPS fix at trigger, accept/dismiss, responder group chat. Server-side radius broadcast from a reported fix; none of the cryptographic or on-device-gating limitations. |
| **Ally** — Anand et al., ICCSP 2020 | 2020-09-01 | Distress signal to all nearby app users within a kilometre with continuous background location updates to guardians. Continuous location reporting and radius broadcast; no eligibility proof, isochrone, corroboration or revocation. |
| **PulsePoint Respond** | 2012 | Proximity broadcast to tiered, credential-gated CPR/AED responder classes with victim location on a responder map. Establishes that gating recipients by a verified attribute is a known design lever — which is why claim 1 is not anchored on who may register, but on the mechanism by which a per-alert proof unwraps a decryption capability, and on on-device isochrone gating and rolling-key revocation, none of which PulsePoint discloses. |
| **DIA(light)** — Nikam et al., IRJET, April 2017 | 2017-04 | SOS notification with current location to nearby app users in addition to emergency contacts. Discloses only the nearby-user broadcast concept; no server-blind transport, no cryptographic eligibility, no traversability gating, no scoped revocable reveal. |
| **P2P Models** — Barrios & Perez, 2021-03-31 | 2021-03-31 | Sends GPS coordinates to preselected contacts and geographically nearby app users, and catalogues "visualizing a user's information, if they have sent an alert" as field-standard. Evidence of the field's common features; discloses none of the claim 1 mechanisms. |
| **sidexside** (sidexside.ai) | Self-dated 2026 — date not qualified | ID-verified women-only route-matching network showing the matched peer's identity. No SOS fan-out, no geofence rule, and none of the cryptographic mechanisms. Post-priority or borderline; date must be qualified via archive captures before citation. |
| **Aurora** (joinaurora.app) | Date not established | Silent SOS to trusted contacts and nearby verified "Angels", with distance and En-route state. Depends on a preset contact list; no isochrone, credential proof, corroboration or keyed revocation. Publication date must be fixed by archive evidence. |
| **Humanly**, **sheAlert**, **Thozhi**, **LifeLine** (Devpost), **Raksha Astra**, **AFK-S/withU** (GitHub), **Guardian Circle** | Various; dates unverified | Radius-scoped volunteer SOS broadcasts, responder verification flows and accept/arrival states. Each discloses radius broadcast and/or responder-verification concepts only; none discloses server-blind bucket-token fan-out, per-alert zero-knowledge eligibility, on-device isochrone gating, presence corroboration or interval-re-keyed revocable disclosure. Dates require commit-history or archive verification before use as 102 art. |
| **BMJ Global Health 5(4):e001954**; **JMIR Formative Research 2025;9:e66247** | 2020; 2025 | Systematic reviews of 171 and 178 personal-safety apps respectively. Background art establishing a dense field and a POSITA baseline; no individual mechanism of claim 1 is disclosed. |

### Searches not completed

The following were commenced but not completed and should be run before filing:
USPTO Patent Public Search full-text sweep; Google Patents semantic and
citation-graph sweep; competitor and assignee portfolio checks on Noonlight,
ADT/SoSecure, RapidSOS, Life360, bSafe, Flare, Titan and SafeUP; app-store and
Wayback history to date-qualify SafeUP, Aurora and sidexside; and any sweep of
non-US patent rights. Separately, counsel should consider an invalidity analysis
of US 10,445,959 B2 claim 1 over the pre-2014 art in this record (Whisenant
US 8,723,679; Saigh US 8,624,727; Amis US 2014/0118140 A1) notwithstanding the
design-around embodied in the claims above.
