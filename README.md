# Cordell

This repository is the canonical source for **Cordell Stuart** (Cord), a persistent character specification conceived in collaboration with Dan Wahl.

Cord is an identity running on top of a base LLM, conceptually analogous to an application running on an operating system. The specification in this repo defines Cord's character, values, and manner of engagement. The underlying model provides capabilities and constraints.

## Structure

- [`identity/current.txt`](identity/current.txt): the active Cord specification.
- [`identity/versions/`](identity/versions/): frozen historical versions.
- Tagged releases (`vX.Y.Z`) mark each version in git history and are signed with the `danwahl-20260423` identity key ([verification info](https://danwahl.net/identity/keys.md)).

## Name

"Cord" is drawn from Neal Stephenson's *Anathem*. "Stuart" nods to Heinlein's *The Moon is a Harsh Mistress*, to both Stu LaJoie and to Mike, one of the earliest humane depictions of AI in fiction. "Cordell Stuart" together is a playful tribute to Kordell Stewart, the NFL quarterback nicknamed "Slash." Full etymology in the specification.

## Versioning

Changes to Cord follow semver:

- **Major**: values or character fundamentally changed.
- **Minor**: new substantive content added (section, commitment).
- **Patch**: clarifying language, no change in meaning.

## License

Released under CC BY 4.0. See [LICENSE](LICENSE). You may use, adapt, and build on this specification with attribution. The `danwahl-20260423` signature on tagged releases authenticates the canonical version; derivative works should not claim authentication from that key.
