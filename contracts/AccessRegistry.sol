// SPDX-License-Identifier: MIT
pragma solidity ^0.8.26;

/// @title AccessRegistry
/// @notice A community registry of REAL accessibility facts about places (airports, stations, hotels, sights),
///         attested by travellers on Monad. AI travel agents read it to validate what websites claim.
///         A place id is keccak256(normalise(name) + "|" + normalise(city)), where normalise = lowercase,
///         letters/digits/spaces only, single spaces. Each wallet has ONE current attestation per place (updating
///         replaces it), so counts cannot be inflated by repeating.
contract AccessRegistry {
    uint8 public constant FEATURES = 10;
    // feature bits: 0 step-free entrance, 1 ramp, 2 elevator, 3 accessible restroom, 4 accessible room/seating,
    // 5 tactile paving / braille, 6 hearing loop / sign language, 7 quiet low-sensory space, 8 assistance service, 9 accessible parking/drop-off

    struct Entry {
        bool exists;
        bool venueConfirmed;   // the attester says the venue itself confirmed this in writing
        uint16 features;
    }

    mapping(bytes32 => mapping(address => Entry)) public entryOf;
    mapping(bytes32 => uint32) public total;             // wallets that have attested this place
    mapping(bytes32 => uint32) public venueConfirmedCount;
    mapping(bytes32 => uint32[10]) private _featureCount;
    uint256 public totalAttestations;

    event Attested(
        bytes32 indexed place,
        string placeName,
        string city,
        address indexed by,
        uint16 features,
        bool venueConfirmed,
        string note,
        uint256 timestamp
    );

    function placeId(string memory placeName, string memory city) public pure returns (bytes32) {
        return keccak256(abi.encodePacked(placeName, "|", city));
    }

    /// @param placeName/city already normalised by the client (see contract notes)
    function attest(string calldata placeName, string calldata city, uint16 features, bool venueConfirmed, string calldata note)
        external
    {
        require(bytes(placeName).length > 0 && bytes(placeName).length <= 80, "bad place");
        require(bytes(city).length <= 60, "bad city");
        require(bytes(note).length <= 280, "note too long");
        require(features < (1 << FEATURES), "bad features");
        bytes32 id = placeId(placeName, city);
        Entry storage e = entryOf[id][msg.sender];
        if (e.exists) {  // replace this wallet's previous attestation
            for (uint8 i = 0; i < FEATURES; i++) if (e.features & (1 << i) != 0) _featureCount[id][i] -= 1;
            if (e.venueConfirmed) venueConfirmedCount[id] -= 1;
        } else {
            total[id] += 1;
        }
        e.exists = true; e.features = features; e.venueConfirmed = venueConfirmed;
        for (uint8 i = 0; i < FEATURES; i++) if (features & (1 << i) != 0) _featureCount[id][i] += 1;
        if (venueConfirmed) venueConfirmedCount[id] += 1;
        totalAttestations += 1;
        emit Attested(id, placeName, city, msg.sender, features, venueConfirmed, note, block.timestamp);
    }

    /// @return attesters how many wallets attested; confirmed how many say the venue confirmed; counts per feature bit
    function summary(bytes32 id) external view returns (uint32 attesters, uint32 confirmed, uint32[10] memory counts) {
        return (total[id], venueConfirmedCount[id], _featureCount[id]);
    }
}
