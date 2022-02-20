import boto3
from moto import mock_organizations, mock_sts
from botocove.cove_host_account import CoveHostAccount
import pytest
from typing import Iterator


@pytest.fixture(scope="module")
def mock_org_session() -> Iterator[boto3.Session]:
    """Uses moto mocking library to allow creation of fake AWS environment.
    This fake environment is present as long as this fixture is passed: does not need
    direct instantiation, but is available for fake AWS environment customisation"""
    with mock_sts():
        with mock_organizations():
            yield boto3.session.Session()


class SmallOrg:
    def __init__(self, session: boto3.Session):
        mock_org_client = session.client("organizations")

        # create org
        mock_org_client.create_organization(FeatureSet="CONSOLIDATED_BILLING")[
            "Organization"
        ]["Id"]
        # Create 3 deep org nest
        root_id = mock_org_client.list_roots()["Roots"][0]["Id"]

        self.new_org1 = mock_org_client.create_organizational_unit(
            ParentId=root_id,
            Name="ou-1",
        )["OrganizationalUnit"]["Id"]
        self.new_org2 = mock_org_client.create_organizational_unit(
            ParentId=self.new_org1,
            Name="ou-2",
        )["OrganizationalUnit"]["Id"]
        self.new_org3 = mock_org_client.create_organizational_unit(
            ParentId=self.new_org2,
            Name="ou-3",
        )["OrganizationalUnit"]["Id"]

        self.account_group_one = []
        for i in range(3):
            acc = mock_org_client.create_account(
                Email=f"mock{i}@mock.com", AccountName=f"mock{i}"
            )["CreateAccountStatus"]["AccountId"]
            # Move account to bottom of OU tree
            mock_org_client.move_account(
                AccountId=acc,
                SourceParentId=root_id,
                DestinationParentId=self.new_org3,
            )
            self.account_group_one.append(acc)

        # Create a second fork from root
        self.new_org4 = mock_org_client.create_organizational_unit(
            ParentId=root_id,
            Name="ou-4",
        )["OrganizationalUnit"]["Id"]
        acc_in_second_ou_fork = mock_org_client.create_account(
            Email="mock4@mock.com", AccountName="mock4"
        )["CreateAccountStatus"]["AccountId"]
        mock_org_client.move_account(
            AccountId=acc_in_second_ou_fork,
            SourceParentId=root_id,
            DestinationParentId=self.new_org4,
        )
        self.account_group_two = [acc_in_second_ou_fork]


def test_get_account_by_ou(mock_org_session: boto3.Session) -> None:

    mock_org = SmallOrg(mock_org_session)
    host_account = CoveHostAccount(
        target_ids=None,
        ignore_ids=None,
        rolename=None,
        role_session_name=None,
        policy=None,
        policy_arns=None,
        org_master=True,
        assuming_session=None,
    )

    results = host_account._get_all_accounts_by_organization_units([mock_org.new_org1])

    assert set(mock_org.account_group_one) == set(results)
    assert mock_org.account_group_two[0] not in results

    results_second = host_account._get_all_accounts_by_organization_units(
        [mock_org.new_org4]
    )
    assert results_second == mock_org.account_group_two
    for g1_acc in mock_org.account_group_one:
        assert g1_acc not in results_second

    results_third = host_account._get_all_accounts_by_organization_units(
        [mock_org.new_org3]
    )
    assert set(mock_org.account_group_one) == set(results_third)
    assert mock_org.account_group_two[0] not in results_third
