export interface VehicleRecord {
  id: number;
  vehicleNumber: string;
  driverName: string;
  material: string;
  status: string;
  entryTime: string;
  exitTime: string;
  quantity: number;
}

export const dashboardSummary = {
  totalVehicles: 48,
  insideVehicles: 22,
  completedTrips: 24,
  alerts: 5
};

export const vehicleRecords: VehicleRecord[] = [
  {
    id: 1,
    vehicleNumber: 'TS09AB1234',
    driverName: 'Ravi Kumar',
    material: 'Sand',
    status: 'Inside Gate',
    entryTime: '08:30 AM',
    exitTime: '-',
    quantity: 12
  },
  {
    id: 2,
    vehicleNumber: 'TS10CD4567',
    driverName: 'Suresh Reddy',
    material: 'Sand',
    status: 'Completed',
    entryTime: '07:45 AM',
    exitTime: '10:15 AM',
    quantity: 15
  },
  {
    id: 3,
    vehicleNumber: 'AP28EF7890',
    driverName: 'Mahesh Rao',
    material: 'Gravel',
    status: 'Inside Gate',
    entryTime: '09:10 AM',
    exitTime: '-',
    quantity: 10
  },
  {
    id: 4,
    vehicleNumber: 'TS08GH2468',
    driverName: 'Prakash',
    material: 'Sand',
    status: 'Alert',
    entryTime: '06:50 AM',
    exitTime: '-',
    quantity: 18
  },
  {
    id: 5,
    vehicleNumber: 'AP29IJ1357',
    driverName: 'Anil Kumar',
    material: 'Sand',
    status: 'Completed',
    entryTime: '06:20 AM',
    exitTime: '09:40 AM',
    quantity: 14
  },
  {
    id: 6,
    vehicleNumber: 'TS07KL9753',
    driverName: 'Naveen',
    material: 'Stone',
    status: 'Inside Gate',
    entryTime: '10:05 AM',
    exitTime: '-',
    quantity: 11
  },
  {
    id: 7,
    vehicleNumber: 'AP30MN8642',
    driverName: 'Venkatesh',
    material: 'Sand',
    status: 'Completed',
    entryTime: '08:00 AM',
    exitTime: '11:20 AM',
    quantity: 16
  },
  {
    id: 8,
    vehicleNumber: 'TS12OP7531',
    driverName: 'Ramesh',
    material: 'Gravel',
    status: 'Alert',
    entryTime: '09:45 AM',
    exitTime: '-',
    quantity: 13
  }
];