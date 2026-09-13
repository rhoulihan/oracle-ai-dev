// Generated data-access layer (godror). Binds by name; reads the
// connection from DB_USER / DB_PASSWORD / DB_DSN.
package datalayer

import (
	"database/sql"
	"os"

	_ "github.com/godror/godror"
)

func Connect() (*sql.DB, error) {
	return sql.Open("godror", `user="`+os.Getenv("DB_USER")+`" password="`+os.Getenv("DB_PASSWORD")+`" connectString="`+os.Getenv("DB_DSN")+`"`)
}

const SQLGetReservation = `SELECT itineraryreservation.reservation_id, itineraryreservation.reservation_status_code, itineraryreservation.ticket_type_code, itineraryreservation.travel_class_code, itineraryreservation.number_in_party
FROM itinerary_reservations itineraryreservation
WHERE itineraryreservation.reservation_id = :b0`

// GetReservation — relational shape
func GetReservation(db *sql.DB, b0 interface{}) (*sql.Rows, error) {
	return db.Query(SQLGetReservation, sql.Named("b0", b0))
}

const SQLPassengerReservations = `SELECT itineraryreservation.reservation_id, itineraryreservation.reservation_status_code
FROM itinerary_reservations itineraryreservation
WHERE itineraryreservation.passenger_id = :b0
ORDER BY itineraryreservation.reservation_id ASC`

// PassengerReservations — relational shape
func PassengerReservations(db *sql.DB, b0 interface{}) (*sql.Rows, error) {
	return db.Query(SQLPassengerReservations, sql.Named("b0", b0))
}

const SQLReservationsByStatus = `SELECT itineraryreservation.reservation_id, itineraryreservation.passenger_id
FROM itinerary_reservations itineraryreservation
WHERE itineraryreservation.reservation_status_code = :b0
ORDER BY itineraryreservation.reservation_id ASC
FETCH FIRST 20 ROWS ONLY`

// ReservationsByStatus — relational shape
func ReservationsByStatus(db *sql.DB, b0 interface{}) (*sql.Rows, error) {
	return db.Query(SQLReservationsByStatus, sql.Named("b0", b0))
}

const SQLReservationPassenger = `SELECT itineraryreservation.reservation_id, passenger.last_name, passenger.email_address
FROM itinerary_reservations itineraryreservation
JOIN passengers passenger ON itineraryreservation.passenger_id = passenger.passenger_id
WHERE itineraryreservation.reservation_id = :b0`

// ReservationPassenger — relational shape
func ReservationPassenger(db *sql.DB, b0 interface{}) (*sql.Rows, error) {
	return db.Query(SQLReservationPassenger, sql.Named("b0", b0))
}
