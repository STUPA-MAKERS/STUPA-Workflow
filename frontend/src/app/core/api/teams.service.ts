/**
 * API of the teams (`/api/teams`, spec 003074).
 *
 * Every Gremium is a team of its own (its inherent team, `gremiumId` set), and a team can
 * have sub-teams (`parentId`). `isMember` and `canManage` are the rights of the caller;
 * the server stays authoritative for every write.
 */
import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import type { Observable } from 'rxjs';
import { API_BASE_URL } from '@core/api/api.config';
import type { GremiumInfo, GremiumInfoSave } from '@core/api/gremien.service';
import type { Uuid } from '@core/api/models';
import { skipLoading } from '@stupa-makers/ui-kit';

export type TeamRole = 'member' | 'manager';

/** The Info of a free team has the shape of the Info of a Gremium. */
export type TeamInfo = GremiumInfo;

/** A team in the list, with the rights of the caller. */
export interface Team {
  readonly id: Uuid;
  readonly name: string;
  /** The Gremium of an inherent team, else null. */
  readonly gremiumId: Uuid | null;
  readonly parentId: Uuid | null;
  readonly parentName: string | null;
  /** The own board of the team. */
  readonly boardId: Uuid | null;
  /** The active members of a free team; null for an inherent team (its Gremium counts). */
  readonly memberCount: number | null;
  readonly isMember: boolean;
  readonly canManage: boolean;
}

/** A member of a team; an inherent team names no role. */
export interface TeamMember {
  readonly principalId: Uuid;
  readonly displayName: string;
  readonly role: TeamRole | null;
}

/** A team with its members (empty for an outsider) and its sub-teams. */
export interface TeamDetail {
  readonly team: Team;
  readonly members: readonly TeamMember[];
  readonly subTeams: readonly Team[];
}

@Injectable({ providedIn: 'root' })
export class TeamsApiService {
  private readonly http = inject(HttpClient);
  private readonly base = `${inject(API_BASE_URL)}/teams`;

  /** Every team by name. */
  list(): Observable<readonly Team[]> {
    return this.http.get<readonly Team[]>(this.base, { context: skipLoading() });
  }

  detail(teamId: Uuid): Observable<TeamDetail> {
    return this.http.get<TeamDetail>(`${this.base}/${teamId}`, { context: skipLoading() });
  }

  /** A new free team (null parent: at the top, needs `team.create`); the caller manages it. */
  create(name: string, parentId: Uuid | null): Observable<TeamDetail> {
    return this.http.post<TeamDetail>(this.base, { name, parentId });
  }

  /** Rename a free team, or move a team (`parentId` null: to the top). */
  patch(teamId: Uuid, body: { readonly name?: string; readonly parentId?: Uuid | null }): Observable<TeamDetail> {
    return this.http.patch<TeamDetail>(`${this.base}/${teamId}`, body);
  }

  remove(teamId: Uuid): Observable<void> {
    return this.http.delete<void>(`${this.base}/${teamId}`);
  }

  /** Add a person to a free team or change the role. */
  setMember(teamId: Uuid, principalId: Uuid, role: TeamRole): Observable<TeamDetail> {
    return this.http.put<TeamDetail>(`${this.base}/${teamId}/members/${principalId}`, { role });
  }

  removeMember(teamId: Uuid, principalId: Uuid): Observable<TeamDetail> {
    return this.http.delete<TeamDetail>(`${this.base}/${teamId}/members/${principalId}`);
  }
  /** The Info tab of a free team (003077): text, links and `canEdit`; members only. */
  info(teamId: Uuid): Observable<TeamInfo> {
    return this.http.get<TeamInfo>(`${this.base}/${teamId}/info`, { context: skipLoading() });
  }

  /** Save text and links (a manager); a stale `version` gives 409 `team_info_version_conflict`. */
  saveInfo(teamId: Uuid, body: GremiumInfoSave): Observable<TeamInfo> {
    return this.http.put<TeamInfo>(`${this.base}/${teamId}/info`, body);
  }

}
