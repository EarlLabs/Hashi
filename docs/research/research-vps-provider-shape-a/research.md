# Which VPS provider for hashi's first box

**Author:** Ohno (`alfred`), `/research` pipeline
**Task id:** `research-vps-provider-shape-a`
**Date:** 2026-09-08
**Status:** draft — **not confirmed by the project owner**
**Question:** the owner lives in Russia and will rent **one** machine abroad,
carrying both the control plane / admin panel and one node (runbook **Shape A**).
Which provider?

> Written in English to match `charter.md`, `README.md` and `docs/deploy/runbook.md`.
> The older `docs/research/product-owner-ohno-4/` is Russian because the persona
> who wrote it was; that is history, not a convention.

---

## 0. Short answer

**Rent a small European provider, in the Netherlands or Germany, pay monthly in
crypto, and treat the first box as disposable.** Do not buy a year. Do not use
Hetzner, DigitalOcean, Vultr, OVH, Oracle or AWS. Do not use Aeza or Beget.

Shortlist and the reasoning are in §3. But the provider is not the most important
thing this research found, and the next section is the one that matters.

---

## 1. The finding that reframes the question

**Shape A — a single foreign box, dialled directly from a Russian network — is
the exact configuration Russia's censor handles best.**

Since roughly June 2025 the TSPU deploys a data-cap rather than a block: a TCP
connection from a **foreign datacenter ASN** is "frozen" after about **15–20 KB
/ ~25 packets** server-to-client. No RST is sent; the client just times out.
Two properties make this severe:

- **It is protocol-agnostic.** It does not care that your traffic is VLESS,
  Reality, WireGuard or anything else. No configuration change defeats it. As
  the 2026 VLESS guide puts it: if the server is frozen by traffic volume or its
  subnet is blocked, *no config saves you — change IP or hosting*.
- **It is applied per subnet, not per host.** The named targets are the ASNs of
  Hetzner, DigitalOcean, Vultr, OVH, Oracle, AWS and Cloudflare. Your box does
  not have to have done anything.

And the thing that still works, per the same community reporting as of mid-2026:
**chained proxies — a Russian VPS in front of a foreign VPS — because the TSPU
generally leaves Russian-to-Russian traffic alone.**

That chain is *precisely* hashi's entry→leaf topology. The architecture this
repository already implements is the one that survives; Shape A is the one that
does not. That is an argument for Shape B/C eventually — not against renting one
box now, because you cannot learn to run the two-box shape without first proving
the one-box pipeline works at all. But it changes **how** you buy:

| Because | Buy this way |
|---|---|
| The first IP is expected to burn | **Monthly**, never annual. No prepay discounts. |
| You will add a Russian entry node later | Pick a provider that also sells **Russian** or near-RU locations, so the second box is one more order, not one more vendor relationship. |
| The panel moves off this box in Shape C | Do not build anything that assumes panel and node share a host. |

**Set your expectation accordingly: Shape A proves the pipeline — panel, SSH
push, subscription link, a stock client accepting it. It is unlikely to give you
a tunnel that survives a Russian mobile network for long.** That is not a defect
in hashi; it is what the 2026 network does to a lone datacenter IP.

---

## 2. Decision axes, and what the evidence says

| # | Axis | What the evidence says | Implication |
|---|---|---|---|
| 1 | **Will they take a Russian customer at all?** | Hetzner terminated *all* customers with Russian postal addresses — announced 2023-12-08, notices 2023-12-15, effective 2024-01-31, citing "changes in the legal regulations". | Hetzner is not an option regardless of its other merits. Assume any large German/EU provider may do the same. |
| 2 | **Is the provider's ASN already throttled?** | The 15–20 KB freeze names Hetzner, DigitalOcean, Vultr, OVH, Oracle, AWS, Cloudflare. | **The decisive axis.** Prefer a provider too small to be worth a CIDR rule. |
| 3 | **Is the provider sanctioned?** | Aeza Group — **OFAC, 2025-07-01** (bulletproof hosting, ransomware). Stark Industries Solutions — **EU, 2025-05**, since rebranded to evade. Beget LLC, Media Land LLC and ML.Cloud — **EU, 2026**. | The set of "hosters popular with Russian users" overlaps heavily with the set of sanctioned entities. This is the trap in every Russian-language "top VPS" listicle. |
| 4 | **Can you actually pay?** | Crypto is the only rail that is not somebody's policy decision. Note the EU's 21st package (2026-07-23) extended prohibitions on Russian ownership of EU-registered crypto-asset services — so an *EU* exchange or EU payment processor may refuse you; self-custody USDT to a non-EU processor is the resilient path. RU-card-accepting foreign hosters exist (RUVDS via a Canadian processor, IHC via MIR, HOSTKEY, Fornex) but have thinned since 2023 financial monitoring. | Prefer **crypto**. A card ties the box to your identity anyway. |
| 5 | **KYC** | Amnezia's own guidance: prefer providers wanting "only an email address instead of an ID scan". Verified example of the modern middle ground: is\*hosting publishes a **risk-based** KYC policy — not universal, triggered by risk scoring, geography and payment method, demanding passport + proof of address + **biometric selfie** within 72 hours when it fires. AlexHost states KYC is not required for crypto payments, but community reports describe ID demands when signing up via VPN with a throwaway email. | "No KYC" is usually "no KYC *until* something flags you". Sign up cleanly: real email, no VPN during checkout, no throwaway domain. |
| 6 | **Does the AUP allow a VPN?** | Several small providers market VPN-on-VPS explicitly. Separately: as of 2026 Russian law now **prohibits hosting providers from servicing VPN services** — which is about Russian hosters, and is the reason the entry node in Shape B/C is a legal exposure the charter already names. | Ask support in writing before paying. Keep the reply. |
| 7 | **Can you replace the IP?** | Amnezia recommends providers offering pre-check or **IP replacement within 24 hours**, and the ability to buy additional IPv4. Check any candidate IP against VirusTotal and Spamhaus *before* paying — a recycled, already-burnt IP is a common and invisible failure. | Treat IP replacement as a **required feature**, not a nicety. It is your recovery path. |
| 8 | **Latency** | Helsinki ≈ 15 ms from Moscow; Amsterdam and Frankfurt ≈ 47–54 ms. Post-2022 rerouting has degraded some paths. | Real but secondary. A 50 ms leaf that works beats a 15 ms leaf that is frozen. |
| 9 | **Price** | Small-provider VPS lands around **$5–7/month** (is\*hosting Lite $5.94; Fornex from ~90 ₽). | Cheap enough that buying two boxes at two providers is a reasonable hedge. |

---

## 3. Shortlist

Ranked for *this* decision — one box, abroad, panel + node, owner in Russia.
**Confidence** reflects how well I could verify the claim, not how good the host is.

| Provider | Where | Pay | KYC | Why it is on the list | Confidence |
|---|---|---|---|---|---|
| **is\*hosting** | 40+ countries incl. NL, DE, FI | cards, e-wallets, "most cryptocurrencies" | **risk-based**, published policy; passport + selfie when triggered | Explicitly markets "set up your own VPN on a VPS"; from **$5.94/mo**; the huge location list means an IP change is an order, not a migration; free DDoS protection. The published KYC policy is a point in its favour — you can read the rule before you are subject to it. | **Medium-high** — verified their own KYC and VPS pages; payment page is vague and needs a support question. |
| **AlexHost** | Moldova | Visa/MC, PayPal, GPay, BTC/ETH/LTC/**XMR**/USDT via xMoney | states none for crypto | Privacy-oriented, Monero accepted, outside both EU and RU jurisdiction. | **Medium** — payment list verified from their own pages; the "no KYC" claim is contradicted by user reports. |
| **Fornex** | DE, NL | cards **and crypto** | unknown | One of the few taking both Russian-usable rails; European jurisdiction; very cheap. | **Low-medium** — sourced from Russian listicles (SEO-heavy), not from primary pages. |
| **IHC** | RU + NL | **MIR card** | unknown | If crypto is genuinely unavailable to you, a MIR-accepting host with a Dutch location is a rare combination. | **Low** — single source. |
| **HOSTKEY** | NL, DE, RU, US | cards | unknown | Established, sells NL VPS, credit-card pay-as-you-go. | **Low** — vendor page only. |

**How to pick between them:** it matters less than §1 implies you'd like. Run the
§5 checklist against the top two, buy the first that passes, and keep the second
as the place you move to when the first IP freezes.

---

## 4. Do not use

| Provider | Reason | Date |
|---|---|---|
| **Hetzner** | Terminates Russian-address customers; *and* named in the throttling set. | 2023-12 → 2024-01 |
| **DigitalOcean, Vultr, OVH, Oracle, AWS, Cloudflare** | Named targets of the 15–20 KB connection freeze; CIDR-level. | since 2025-06 |
| **Aeza Group** | **OFAC-sanctioned.** Also heavily recommended in Russian-language guides — do not be misled by its popularity. | 2025-07-01 |
| **Stark Industries Solutions** | **EU-sanctioned**; rebranded to evade, so it may reach you under another name. | 2025-05 |
| **Beget LLC** | **EU-sanctioned.** Sits at the top of several current Russian "best VPS" listicles. | 2026 |
| **Media Land LLC / ML.Cloud** | **EU-sanctioned** bulletproof hosting. | 2026 |
| **VDSina / MCHost** | Not sanctioned, but their NL/DE equipment was **powered off without warning** when a Dutch datacenter disconnected MIRhosting. A live demonstration of the political-supply-chain risk. | 2026-06 |

---

## 5. Before you pay — a checklist

1. **Ask support, in writing:** "Do you permit running a personal VPN / proxy on
   a VPS?" and "Can I have the IP replaced if it becomes unreachable from a
   specific country, and how fast?" Keep both answers.
2. **Check the IP they offer** on VirusTotal and Spamhaus before the first
   payment. A recycled burnt IP looks identical to a clean one until nothing works.
3. **Sign up cleanly** — real email, no VPN during checkout — so the risk engine
   never fires and you never face the 72-hour selfie demand.
4. **Buy one month.**
5. **Register a domain for the panel** and point its A record at the box *before*
   bootstrapping — Caddy asks a CA for a certificate the moment it starts
   (`runbook.md`, "DNS").
6. **Test from your actual phone on mobile data**, not from home Wi-Fi. The
   difference between the two is the entire subject of this research.

---

## 6. What this means for hashi specifically

**Good news — the tree already does the right things.**

- `edge/transports/vless_reality/` already sets `"flow": "xtls-rprx-vision"` on
  both the server (`server.j2:34`) and the client URI (`render.py:69`). The 2026
  guide names Vision as the one non-optional element: without it, VLESS+Reality
  is caught by TLS-in-TLS packet-length analysis. We are not exposed to that.
- The client fingerprint is a **per-node parameter** (`render.py:73`,
  `params["fingerprint"]`), not a constant — so the guide's advice to move from a
  Chrome to a Firefox or QQ fingerprint is a panel edit, not a code change.
- `decoy_host` is required per node with no project default (`params.py:47`) —
  which is the charter rule, and independently the guide's advice to avoid the
  overused Google/Microsoft/Amazon/Cloudflare SNIs.
- The runbook's rule "never plain WireGuard to a friend from a Russian mobile
  network" is confirmed: standard OpenVPN and WireGuard have not passed TSPU
  filters since late 2025. Only obfuscated modes work.

**Two findings that are actionable in the tree, and neither is a provider question.**

- **Our Xray is two years stale.** `edge/bootstrap/node_stack.py:69` pins
  `ghcr.io/xtls/xray-core:1.8.24`. Field guidance for the 2026 Russian network
  says to run **at least Xray-core 25.12.8** specifically to avoid detection —
  Xray moved to date-based versioning, so 1.8.24 is roughly two years behind, and
  a client fingerprint that old is long since catalogued. `scripts/fetch-upstream-checkers.sh`
  pins the same `v1.8.24` for the validating binary. Worth a backlog item; I have
  not raised one, because bumping a data-plane pin is a decision with a security
  argument on both sides (new upstream = new defaults = new detectability) and it
  belongs to the owner, not to a research report. *Confidence: the pin is fact;
  the "25.12.8" threshold is one community source.*
- **Port 443 may be the wrong default in Russia, and the runbook says the
  opposite.** `runbook.md` reasons that "Reality's whole camouflage is *being* on
  443" and warns that an odd port is itself a signal. The 2026 field reporting
  says that inside Russia the reverse now holds: VLESS+Reality on standard 443 is
  blocked near-instantly, while moving to **port 47000+** restores roughly 80% of
  throughput; QUIC and UDP/443 are effectively dead. Both statements can be true —
  443 is better camouflage *in general*, and worse *against this specific censor*.
  The runbook should probably carry the caveat. *Confidence: medium — one
  vendor-authored analysis plus community reports, no measurement of my own.*

**Bad news — one charter criterion is not reachable this way.**

Criterion 1, "survives a mobile whitelist shutdown", cannot be met by *any*
foreign box, from any provider, at any price. Under whitelist mode the reachable
set is roughly 57 **Russian** services — RIA, VK, OK, Mail.ru, Max, Yandex, Ozon,
Wildberries, Avito, regional government sites, Maxim taxi, Gismeteo. A foreign IP
is not on that list and cannot be. No provider choice changes this, and this
research should not be read as offering one.

**A useful asymmetry.** The freeze is a *per-connection data cap*, and a
subscription payload is a few kilobytes. So under throttling the delivery
endpoint may well keep working while the tunnel dies — friends could still
*fetch* a new config from a box whose tunnel is frozen. That is worth knowing
before you conclude a box is fully dead.

**A Shape A risk worth naming.** Panel and node share one IP. When that IP is
frozen you lose the tunnel *and* the panel you would use to rotate away from it.
Shape C separates them for exactly this reason. Mitigation for now: SSH still
works (SSH/SFTP are reported to pass unrestricted on any port), so the box stays
administrable even when HTTPS is capped.

---

## 7. Open questions for the owner

1. **Which payment rail do you actually have?** Crypto (self-custodied USDT/XMR)
   or a card? This is the one answer that would narrow §3 to a single row, and I
   deliberately did not assume it.
2. **Do you have a domain for the panel?** Shape A needs one before bootstrap.
3. **Do you accept that Shape A cannot prove criterion 1** — and that it is a
   pipeline rehearsal, with the two-box shape as the real target?

---

## 8. What this research does not establish

- **No provider was tested.** Every claim here is documentary. The only real test
  is your phone on mobile data.
- **Blocking state changes weekly.** Everything in §2 and §4 is a snapshot dated
  2026-09-08 and will decay.
- **Sanctions research is not legal advice.** §4 names designations as a
  practical hazard — payment failure, seizure, sudden disappearance — not as an
  opinion about your legal position.
- **Some of §3 rests on SEO-heavy Russian listicles**, marked Low confidence.
  Those rows are leads to verify, not recommendations.
- **The `fingerprint`, `decoy_host` and SNI advice in §6 is not a security
  review** of our Reality profile. It is one guide's 2026 field reporting lining
  up with what the tree already does.

---

## Sources

Graded: **[P]** primary/authoritative · **[C]** technical community · **[J]**
journalism · **[V]** vendor/marketing · **[S]** SEO listicle, treat as a lead only.

- [J] [Russia's internet censorship in 2026 — Zona Media](https://en.zona.media/article/2026/04/07/russian_internet_censorship_2026) — whitelist contents, VLESS blocking, app-level detection mandate
- [J] [The 16-kilobyte curtain — Zona Media](https://en.zona.media/article/2025/06/19/cloudflare) — the data-cap method, affected providers, June 2025 timeline
- [C] [net4people/bbs issue #490](https://github.com/net4people/bbs/issues/490) — the freeze mechanism, SSH exemption, ASN scope
- [C] [pbldbl/vless-blocking-2026-guide](https://github.com/pbldbl/vless-blocking-2026-guide) — three detection layers, Vision requirement, SNI and fingerprint guidance, diagnostic tree
- [J] [August's VPN crackdown ran on data Russia's own apps collected — Meduza](https://meduza.io/en/feature/2026/08/19/august-s-vpn-crackdown-in-russia-ran-on-data-the-country-s-own-apps-had-already-collected-on-their-users) — exit-IP detection, hosting-network flagging
- [V] [How to Choose a Hoster for Amnezia Self-Hosted](https://amnezia.org/blog/how-to-choose-vps-for-self-hosted-vpn) — small-provider guidance, IP reputation, KYC and crypto advice
- [V] [Amnezia Russia digest, June 2026](https://amnezia.org/blog/amnezia-shutdown-digest-june-2026-russia) — MIRhosting power-off, the anti-VPN hosting law
- [P] [OFAC sanctions Aeza Group — TRM Labs](https://www.trmlabs.com/resources/blog/treasury-sanctions-global-bulletproof-hosting-service-aeza-group-for-enabling-cybercriminal-activity) / [US Treasury](https://www.globalsecurity.org/security/library/news/2025/07/sec-250701-treasury01.htm)
- [P] [EU sanctions, 2026-07-13 — Council of the EU](https://www.consilium.europa.eu/en/press/press-releases/2026/07/13/russian-cyber-attacks-and-destabilising-activities-council-sanctions-nine-individuals-and-four-entities/) — Beget, Media Land, ML.Cloud
- [P] [EU 21st sanctions package, 2026-07-23 — Council of the EU](https://www.consilium.europa.eu/en/press/press-releases/2026/07/23/21st-package-of-sanctions-eu-hits-russian-energy-financial-services-and-crypto-hard/) — crypto-service restrictions
- [J] [Bulletproof host Stark Industries evades EU sanctions — Krebs on Security](https://krebsonsecurity.com/2025/09/bulletproof-host-stark-industries-evades-eu-sanctions/)
- [J] [Hetzner terminates Russian customers](https://mangohost.net/blog/hetzner-announces-termination-of-services-to-russian-customers-migrate-asap/) — quotes Hetzner's notice; secondary source for a primary quote
- [V] [is\*hosting VPS](https://ishosting.com/en/vps) · [KYC policy](https://ishosting.com/en/kyc-policy) · [payment methods](https://ishosting.com/en/payment-methods)
- [V] [AlexHost crypto payment](https://alexhost.com/vps-with-cryptocurrency/) · [payment FAQ](https://alexhost.com/faq/what-pyment-methods-do-we-accept-for-hosting-services/)
- [C] [Alexhost now requiring KYC? — LowEndTalk](https://lowendtalk.com/discussion/203120/alexhost-now-requiring-kyc)
- [V] [Russia's TSPU to 2030 — tgvpn.io](https://tgvpn.io/en/tspu-dpi-russia-2030-analysis.html) — confirms the chained-proxy exemption verbatim; source for the port-47000 and empty-SNI claims, and for Shadowsocks-2022 / xHTTP surviving
- [J] [Russians dig tunnels around the Kremlin's firewall — Cybernews](https://cybernews.com/security/ussians-bypass-kremlin-firewall-with-diy-proxies/) — independent confirmation of the RU-bridge → foreign-exit pattern
- [C] [How to set up Xray Reality on a cheap VPS — works in China and Russia (2026) — LowEndTalk](https://lowendtalk.com/discussion/217868/how-to-set-up-xray-reality-on-a-cheap-vps-works-in-china-and-russia-2026) — source for the Xray-core ≥ 25.12.8 threshold
- [C] [Network latency from Moscow to European countries — LowEndTalk](https://lowendtalk.com/discussion/179707/network-latency-from-moscow-russia-to-some-european-countries) · [WonderNetwork Moscow pings](https://wondernetwork.com/pings/Moscow)
- [S] [ТОП-11 VPS в России 2026 — vc.ru](https://vc.ru/top-raiting/2628093-luchshie-vps-v-rossii-top-11-provayderov) · [VPS за крипту — vc.ru](https://vc.ru/top-raiting/2629167-luchshie-vps-dlya-oplaty-kriptovalyutoy) · [Hosting in Russia — dieg.info](https://dieg.info/en/tsod/russia-en/) — provider leads only
- [S] [RUVDS foreign-card payment — russiable.com](https://russiable.com/russian-vps-hosting/) · [IHC MIR-card VPS](https://www.ihc.host/vps-mir-card.html) · [HOSTKEY NL VPS](https://hostkey.com/vps/netherland-vps/)
