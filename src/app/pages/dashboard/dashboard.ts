import { Component } from '@angular/core';
import { dashboardSummary, vehicleRecords, VehicleRecord } from '../../data/sample-data';

@Component({
  selector: 'app-dashboard',
  imports: [],
  templateUrl: './dashboard.html',
  styleUrl: './dashboard.scss',
})
export class Dashboard {
   summary = dashboardSummary;
  vehicles: VehicleRecord[] = vehicleRecords;

  selectedFilter = 'All Vehicles';

  get filteredVehicles(): VehicleRecord[] {
    if (this.selectedFilter === 'All Vehicles') {
      return this.vehicles;
    }

    return this.vehicles.filter(
      vehicle => vehicle.status === this.selectedFilter
    );
  }

  changeFilter(filter: string): void {
    this.selectedFilter = filter;
  }

  getStatusClass(status: string): string {
    if (status === 'Completed') {
      return 'status-success';
    }

    if (status === 'Inside Gate') {
      return 'status-info';
    }

    if (status === 'Alert') {
      return 'status-danger';
    }

    return 'status-neutral';
  }
}
