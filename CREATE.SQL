-- CREATE.SQL
-- shows table
CREATE TABLE shows (
    show_id VARCHAR(255) PRIMARY KEY,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- seats table
CREATE TABLE seats (
    seat_id VARCHAR(255) NOT NULL,
    show_id VARCHAR(255) NOT NULL REFERENCES shows(show_id) ON DELETE CASCADE,
    status VARCHAR(20) NOT NULL DEFAULT 'available', -- 'available', 'held', 'booked'
    hold_id UUID,
    hold_expires_at TIMESTAMP WITH TIME ZONE,
    PRIMARY KEY (show_id, seat_id),
    CHECK (status IN ('available', 'held', 'booked'))
);

-- holds table (for tracking and cleanup)
CREATE TABLE holds (
    hold_id UUID PRIMARY KEY,
    show_id VARCHAR(255) NOT NULL REFERENCES shows(show_id) ON DELETE CASCADE,
    seat_ids TEXT[] NOT NULL,
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- bookings table
CREATE TABLE bookings (
    booking_id UUID PRIMARY KEY,
    show_id VARCHAR(255) NOT NULL REFERENCES shows(show_id) ON DELETE CASCADE,
    seat_ids TEXT[] NOT NULL,
    booked_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Indexes for performance
CREATE INDEX idx_seats_show_status ON seats(show_id, status);
CREATE INDEX idx_seats_hold_expires ON seats(hold_expires_at) WHERE status = 'held';
CREATE INDEX idx_holds_expires ON holds(expires_at);
CREATE INDEX idx_holds_show ON holds(show_id);