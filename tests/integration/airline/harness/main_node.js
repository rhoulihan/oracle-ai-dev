const repo = require('./repository.js');
function norm(v){ if (v instanceof Date) return v.toISOString(); return v; }
function rowsToArrays(rows){ return rows.map(r => Object.values(r).map(norm)); }
(async () => {
  const conn = await repo.getConnection();
  const out = {
    get_reservation:        rowsToArrays(await repo.getReservation(conn, {b0:1500})),
    passenger_reservations: rowsToArrays(await repo.passengerReservations(conn, {b0:5})),
    reservations_by_status: rowsToArrays(await repo.reservationsByStatus(conn, {b0:"CONFIRMED"})),
    reservation_passenger:  rowsToArrays(await repo.reservationPassenger(conn, {b0:1500})),
  };
  await conn.close();
  process.stdout.write(JSON.stringify(out));
})().catch(e => { console.error(e); process.exit(1); });
