import { Modal } from "./Modal";

type DslHelpModalProps = {
  open: boolean;
  onClose: () => void;
};

export function DslHelpModal({ open, onClose }: DslHelpModalProps) {
  return (
    <Modal open={open} title="DSL reference" onClose={onClose} wide>
      <div className="dsl-help">
        <p className="hint" style={{ marginTop: 0 }}>
          Queries use <code>field:value</code> predicates combined with <code>AND</code>, <code>OR</code>, and{" "}
          <code>NOT</code>. Use parentheses to group clauses. This page previews up to 50 rows; exports use the same DSL
          for the full match set.
        </p>

        <h3>Field matching</h3>
        <table className="dsl-help__table">
          <thead>
            <tr>
              <th>Mode</th>
              <th>Example</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>Exact</td>
              <td className="mono">
                <code>email:john@outlook.com</code>
              </td>
            </tr>
            <tr>
              <td>Prefix</td>
              <td className="mono">
                <code>username:john*</code>
              </td>
            </tr>
            <tr>
              <td>Suffix</td>
              <td className="mono">
                <code>phone:*7434</code>
              </td>
            </tr>
            <tr>
              <td>Substring</td>
              <td className="mono">
                <code>email:*outlook*</code>
              </td>
            </tr>
            <tr>
              <td>Email domain</td>
              <td className="mono">
                <code>email.domain:outlook.com</code>
              </td>
            </tr>
            <tr>
              <td>Phone country prefix</td>
              <td className="mono">
                <code>phone.country:+34</code>
              </td>
            </tr>
          </tbody>
        </table>

        <h3>Lead fields</h3>
        <p className="hint">
          phone, email, username, id_card, full_name, first_name, last_name, dob, gender, address, city, country, zip,
          ip, user_agent, isp, phone_carrier, password, password_hash, last_seen
        </p>

        <h3>Tags</h3>
        <p className="hint">Open Tags (next to DSL reference) and click a chip to append a filter, or write:</p>
        <table className="dsl-help__table">
          <thead>
            <tr>
              <th>Filter</th>
              <th>Example</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>By tag name</td>
              <td className="mono">
                <code>tag:breach-2024</code>
              </td>
            </tr>
            <tr>
              <td>By tag type</td>
              <td className="mono">
                <code>tag.type:LEAK</code>
              </td>
            </tr>
            <tr>
              <td>By breach year</td>
              <td className="mono">
                <code>tag.breach_date:2024</code>
              </td>
            </tr>
            <tr>
              <td>By breach date</td>
              <td className="mono">
                <code>tag.breach_date:2024-03-15</code>
              </td>
            </tr>
          </tbody>
        </table>
        <p className="hint">Tag names are case-insensitive. Wildcards do not apply to tag predicates.</p>

        <h3>Boolean logic</h3>
        <table className="dsl-help__table">
          <thead>
            <tr>
              <th>Goal</th>
              <th>Example</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>Combine conditions</td>
              <td className="mono">
                <code>email:*@example.com AND tag:smoke-tag</code>
              </td>
            </tr>
            <tr>
              <td>Either condition</td>
              <td className="mono">
                <code>tag:breach-a OR tag:breach-b</code>
              </td>
            </tr>
            <tr>
              <td>Exclude</td>
              <td className="mono">
                <code>email:*@example.com AND NOT tag:archived</code>
              </td>
            </tr>
            <tr>
              <td>Group clauses</td>
              <td className="mono">
                <code>(email:*@a.com OR email:*@b.com) AND tag:leak</code>
              </td>
            </tr>
          </tbody>
        </table>

        <div className="btn-row">
          <button type="button" onClick={onClose}>
            Close
          </button>
        </div>
      </div>
    </Modal>
  );
}
