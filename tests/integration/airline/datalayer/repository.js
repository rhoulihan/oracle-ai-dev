// Generated data-access layer (node-oracledb). Binds by name; reads the
// connection from DB_USER / DB_PASSWORD / DB_DSN.
const oracledb = require('oracledb');

async function getConnection() {
  return oracledb.getConnection({ user: process.env.DB_USER,
    password: process.env.DB_PASSWORD, connectString: process.env.DB_DSN });
}

const SQL_GET_RESERVATION = `SELECT itineraryreservation.reservation_id, itineraryreservation.reservation_status_code, itineraryreservation.ticket_type_code, itineraryreservation.travel_class_code, itineraryreservation.number_in_party
FROM itinerary_reservations itineraryreservation
WHERE itineraryreservation.reservation_id = :b0`;

// get_reservation — relational shape
async function getReservation(conn, { b0 }) {
  const r = await conn.execute(SQL_GET_RESERVATION, { b0 },
    { outFormat: oracledb.OUT_FORMAT_OBJECT });
  return r.rows;
}

const SQL_PASSENGER_RESERVATIONS = `SELECT itineraryreservation.reservation_id, itineraryreservation.reservation_status_code
FROM itinerary_reservations itineraryreservation
WHERE itineraryreservation.passenger_id = :b0
ORDER BY itineraryreservation.reservation_id ASC`;

// passenger_reservations — relational shape
async function passengerReservations(conn, { b0 }) {
  const r = await conn.execute(SQL_PASSENGER_RESERVATIONS, { b0 },
    { outFormat: oracledb.OUT_FORMAT_OBJECT });
  return r.rows;
}

const SQL_RESERVATIONS_BY_STATUS = `SELECT itineraryreservation.reservation_id, itineraryreservation.passenger_id
FROM itinerary_reservations itineraryreservation
WHERE itineraryreservation.reservation_status_code = :b0
ORDER BY itineraryreservation.reservation_id ASC
FETCH FIRST 20 ROWS ONLY`;

// reservations_by_status — relational shape
async function reservationsByStatus(conn, { b0 }) {
  const r = await conn.execute(SQL_RESERVATIONS_BY_STATUS, { b0 },
    { outFormat: oracledb.OUT_FORMAT_OBJECT });
  return r.rows;
}

const SQL_RESERVATION_PASSENGER = `SELECT itineraryreservation.reservation_id, passenger.last_name, passenger.email_address
FROM itinerary_reservations itineraryreservation
JOIN passengers passenger ON itineraryreservation.passenger_id = passenger.passenger_id
WHERE itineraryreservation.reservation_id = :b0`;

// reservation_passenger — relational shape
async function reservationPassenger(conn, { b0 }) {
  const r = await conn.execute(SQL_RESERVATION_PASSENGER, { b0 },
    { outFormat: oracledb.OUT_FORMAT_OBJECT });
  return r.rows;
}

module.exports = { getConnection, getReservation, passengerReservations, reservationsByStatus, reservationPassenger };